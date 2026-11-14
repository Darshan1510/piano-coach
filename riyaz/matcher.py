"""Wait-mode and play-along matchers (PLAN 6.4).

- A stop point = one start time (beat) in the song. Its expected set = all notes that start at
  this time, for the active hands.
- The song continues when all expected keys are down at the same time (keys together), or were
  pressed in order within 300 ms (config.WAIT_CHORD_WINDOW_S).
- A wrong key (not in the expected set) does not continue the song. It is logged.

Only presses after a stop became the current stop count: a key that repeats (E E E) must be
pressed again. This module has no clock and no MIDI: tests feed it events directly.

Play-along (PlayMatcher, Phase 4): each expected note has a time window (config.py). A key press
matches the earliest unmatched note with the same key inside the window: perfect / good / early /
late. Exception: when the earliest note is more than "good" (120 ms) away and a later note with the
same key is within "good", the nearest note matches (fast repeated keys after a missed note).
DECISIONS.md Phase 4 + review fixes. A press with no match is an extra note; 1 or 2 keys from an
expected note at that moment it is a wrong note (likely slip). A note with no press inside the window is missed. Note length:
"short" when held less than 60% of a note of 1 beat or more. Scores: score_of().
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

from . import config

EPS = 1e-6


@dataclass(frozen=True)
class Stop:
    index: int
    beat: float
    pitches: frozenset[int]
    notes: tuple[dict, ...]


@dataclass
class WaitMatcher:
    stops: list[Stop]
    window: float = config.WAIT_CHORD_WINDOW_S
    index: int = 0
    errors: list[dict] = field(default_factory=list)
    _presses: dict[int, float] = field(default_factory=dict)  # pitch -> press time (current stop)
    _down: set[int] = field(default_factory=set)

    @classmethod
    def for_song(cls, song: dict, hands, start: float | None = None, end: float | None = None,
                 window: float = config.WAIT_CHORD_WINDOW_S) -> "WaitMatcher":
        return cls(stops=build_stops(song, hands, start, end), window=window)

    @property
    def current(self) -> Stop | None:
        return self.stops[self.index] if self.index < len(self.stops) else None

    @property
    def done(self) -> bool:
        return self.index >= len(self.stops)

    def reset(self) -> None:
        self.index = 0
        self._presses.clear()

    def press(self, pitch: int, t: float, beat: float | None = None) -> dict:
        """A key went down. Returns {"result": "hit" | "wrong" | "done", "advanced": bool, ...}."""
        self._down.add(pitch)
        stop = self.current
        if stop is None:
            return {"result": "done", "advanced": False}
        if pitch not in stop.pitches:
            err = {"stop": stop.index, "pitch": pitch, "expected": sorted(stop.pitches), "t": t, "beat": beat}
            self.errors.append(err)
            return {"result": "wrong", "advanced": False, "stop": stop.index, "expected": sorted(stop.pitches)}
        self._presses[pitch] = t
        if self._complete(t):
            self.index += 1
            self._presses.clear()
            return {"result": "hit", "advanced": True, "stop": stop.index}
        return {"result": "hit", "advanced": False, "stop": stop.index}

    def release(self, pitch: int, t: float) -> None:
        self._down.discard(pitch)

    def _complete(self, t: float) -> bool:
        stop = self.current
        assert stop is not None
        for p in stop.pitches:
            pt = self._presses.get(p)
            if pt is None:
                return False
            # Down now (keys together), or pressed in order within the window.
            if p not in self._down and t - pt > self.window + EPS:
                return False
        return True


def build_stops(song: dict, hands, start: float | None = None, end: float | None = None) -> list[Stop]:
    """Stop points for the active hands, in the beat range [start, end)."""
    hands = set(hands)
    groups: dict[float, list[dict]] = {}
    for n in song["notes"]:
        if n["hand"] not in hands:
            continue
        if start is not None and n["start"] < start - EPS:
            continue
        if end is not None and n["start"] >= end - EPS:
            continue
        key = round(n["start"], 6)
        groups.setdefault(key, []).append(n)
    stops = []
    for i, beat in enumerate(sorted(groups)):
        notes = tuple(sorted(groups[beat], key=lambda n: n["pitch"]))
        stops.append(Stop(index=i, beat=beat, pitches=frozenset(n["pitch"] for n in notes), notes=notes))
    return stops


# ---------------------------------------------------------------------- play-along (Phase 4)


@dataclass
class PlayNote:
    index: int
    note: dict
    start: float
    pitch: int
    grade: str | None = None  # perfect | good | early | late | miss (None = not decided yet)
    err: float | None = None  # seconds, + = late
    press_beat: float | None = None
    vel: int | None = None
    held: float | None = None  # beats the key was down
    short: bool = False
    slip: int | None = None  # the wrong neighbor key that the user pressed for this note

    @property
    def hit(self) -> bool:
        return self.grade in ("perfect", "good", "early", "late")

    def clear(self) -> None:
        self.grade = self.err = self.press_beat = self.vel = self.held = self.slip = None
        self.short = False

    def log(self) -> dict:
        n = self.note
        return {"i": self.index, "start": self.start, "dur": n["dur"], "pitch": self.pitch, "hand": n["hand"],
                "finger": n.get("finger"), "grade": self.grade or "miss",
                "err_ms": None if self.err is None else round(self.err * 1000.0, 1), "short": self.short,
                "vel": self.vel, "want_vel": n.get("vel"), "slip": self.slip}


@dataclass
class PlayMatcher:
    notes: list[PlayNote]
    perfect: float = config.PLAY_PERFECT_S
    good: float = config.PLAY_GOOD_S
    window: float = config.PLAY_WINDOW_S
    neighbor: int = config.PLAY_NEIGHBOR
    extras: list[dict] = field(default_factory=list)
    floor: float = -math.inf  # notes before this beat are closed (after "Continue from here")
    _held: dict[int, PlayNote] = field(default_factory=dict)
    _ptr: int = 0  # notes before this index are decided (hit or missed)

    def __post_init__(self) -> None:
        self.notes.sort(key=lambda n: (n.start, n.pitch))
        self._starts = [n.start for n in self.notes]

    @classmethod
    def for_song(cls, song: dict, hands, start: float | None = None, end: float | None = None, **kw) -> "PlayMatcher":
        hands = set(hands)
        chosen = [n for n in song["notes"] if n["hand"] in hands
                  and (start is None or n["start"] >= start - EPS) and (end is None or n["start"] < end - EPS)]
        chosen.sort(key=lambda n: (n["start"], n["pitch"]))
        return cls(notes=[PlayNote(i, n, float(n["start"]), int(n["pitch"])) for i, n in enumerate(chosen)], **kw)

    # ---- input

    def _near(self, beat: float, wb: float) -> range:
        lo = bisect.bisect_left(self._starts, beat - wb - EPS)
        hi = bisect.bisect_right(self._starts, beat + wb + EPS)
        return range(lo, hi)

    def _candidate(self, pitch: int, beat: float, rate: float, near: range | None = None) -> PlayNote | None:
        """The note that a press of `pitch` at `beat` matches, or None. The earliest unmatched note
        whose window holds the press (with the same key twice in a row, a late press for the first
        note must not take the second), but the nearest note when the earliest is more than "good"
        away and a later same-key note is within "good" (fast repeated keys after a missed note).
        Notes already graded "miss" are closed (a slower speed makes the window wider)."""
        if near is None:
            near = self._near(beat, self.window * rate)
        cands = [self.notes[i] for i in near
                 if self.notes[i].pitch == pitch and self.notes[i].grade is None
                 and self.notes[i].start >= self.floor - EPS]
        if not cands:
            return None
        gb = self.good * rate + EPS
        first = min(cands, key=lambda n: n.start)
        if abs(beat - first.start) <= gb:
            return first
        nearest = min(cands, key=lambda n: (abs(beat - n.start), n.start))
        if nearest is not first and abs(beat - nearest.start) <= gb:
            return nearest
        return first

    def candidate_err(self, pitch: int, beat: float, rate: float) -> float | None:
        """Seconds between a press and the note that it would match (None: no match). No change."""
        if beat < self.floor - self.window * rate - EPS:
            return None
        n = self._candidate(pitch, beat, rate)
        return None if n is None else abs(beat - n.start) / rate

    def holds(self, pitch: int) -> bool:
        return pitch in self._held

    def press(self, pitch: int, t: float, beat: float, rate: float, vel: int | None = None) -> dict:
        """A key went down at song beat `beat` (rate = beats per second now)."""
        wb = self.window * rate
        if beat < self.floor - wb - EPS:
            return {"result": "ignored"}
        near = self._near(beat, wb)
        best = self._candidate(pitch, beat, rate, near)
        if best is not None:
            err = (beat - best.start) / rate
            a = abs(err)
            best.grade = "perfect" if a <= self.perfect + 1e-9 else "good" if a <= self.good + 1e-9 \
                else ("early" if err < 0 else "late")
            best.err, best.press_beat, best.vel = err, beat, vel
            if best.slip is not None:  # a wrong neighbor key first, then the right key: a normal extra note
                best.slip = None
                for e in self.extras:
                    if e["slip_of"] == best.index:
                        e["slip_of"] = None
            self._held[pitch] = best
            return {"result": "hit", "grade": best.grade, "err_ms": round(err * 1000.0, 1), "note": best.index,
                    "finger": best.note.get("finger"), "hand": best.note["hand"]}
        # A key of a closed note (before "Continue from here"): not counted.
        if any(self.notes[i].pitch == pitch and self.notes[i].start < self.floor - EPS for i in near):
            return {"result": "ignored"}
        expected = [self.notes[i] for i in near if self.notes[i].start >= self.floor - EPS]
        slip_of = None
        for n in expected:
            d = abs(n.pitch - pitch)
            if 1 <= d <= self.neighbor and not n.hit and n.slip is None:
                key = (abs(n.start - beat), d)
                if slip_of is None or key < slip_of[0]:
                    slip_of = (key, n)
        extra = {"beat": round(beat, 4), "pitch": pitch, "vel": vel, "slip_of": None}
        res = {"result": "wrong", "slip": False, "expected": sorted({n.pitch for n in expected})}
        if slip_of is not None:
            n = slip_of[1]
            n.slip = pitch
            extra["slip_of"] = n.index
            res.update(slip=True, intended=n.pitch, finger=n.note.get("finger"), hand=n.note["hand"], note=n.index)
        self.extras.append(extra)
        return res

    def release(self, pitch: int, t: float, beat: float) -> dict | None:
        n = self._held.pop(pitch, None)
        if n is None or n.press_beat is None:
            return None
        n.held = max(0.0, beat - n.press_beat)
        checked = n.note["dur"] >= config.PLAY_SHORT_MIN_BEATS - EPS
        n.short = checked and n.held < config.PLAY_SHORT_RATIO * n.note["dur"] - EPS
        return {"note": n.index, "short": n.short, "checked": checked}

    # ---- time

    def advance(self, beat: float, rate: float) -> list[PlayNote]:
        """Notes whose window is over and that got no press: missed. Returns the new ones."""
        wb = self.window * rate
        out = []
        while self._ptr < len(self.notes) and self.notes[self._ptr].start + wb < beat - EPS:
            n = self.notes[self._ptr]
            if n.grade is None and n.start >= self.floor - EPS:
                n.grade = "miss"
                out.append(n)
            self._ptr += 1
        return out

    def first_missed_after(self, beat: float, rate: float) -> PlayNote | None:
        """The first missed note with no key at all (not a slip) whose window opened after `beat`."""
        wb = self.window * rate
        for n in self.notes[:self._ptr]:
            if n.grade == "miss" and n.slip is None and n.start - wb > beat + EPS and n.start >= self.floor - EPS:
                return n
        return None

    def rewind(self, beat: float) -> None:
        """Play again from `beat` ("Continue from here"): notes from there get a new chance."""
        self.floor = beat
        for n in self.notes:
            if n.start >= beat - EPS:
                n.clear()
        self.extras = [e for e in self.extras if e["beat"] < beat - EPS]
        self._held.clear()
        self._ptr = bisect.bisect_left(self._starts, beat - EPS)

    def reset(self) -> None:
        """A new pass of a repeated part."""
        for n in self.notes:
            n.clear()
        self.extras = []
        self.floor = -math.inf
        self._held.clear()
        self._ptr = 0

    def finish(self, end_beat: float | None = None) -> dict:
        """The run is over: every note without a press is missed. Returns the score."""
        for n in self.notes:
            if n.grade is None:
                n.grade = "miss"
            if n.hit and n.held is None and n.press_beat is not None and end_beat is not None:
                n.held = max(0.0, end_beat - n.press_beat)  # still down at the end: not short
        self._ptr = len(self.notes)
        return self.score()

    # ---- results

    def log(self) -> dict:
        return {"notes": [n.log() for n in self.notes], "extras": [dict(e) for e in self.extras]}

    def score(self) -> dict:
        lg = self.log()
        return score_of(lg["notes"], lg["extras"])


def score_of(notes: list[dict], extras: list[dict]) -> dict:
    """Scores of a run (or of a part of it) from the log (PLAN 6.4).

    accuracy = notes hit / (notes + extra notes that are not slips). A slip is counted one time
    (its note is missed). timing = perfect + good, % of the notes hit. length = notes of 1 beat or
    more held long enough, % of those notes hit. total = accuracy x (0.6 + 0.25 timing + 0.15 length).
    """
    total_n = len(notes)
    hits = [n for n in notes if n["grade"] in ("perfect", "good", "early", "late")]
    counts = {g: sum(1 for n in notes if n["grade"] == g) for g in ("perfect", "good", "early", "late", "miss")}
    stray = [e for e in extras if e.get("slip_of") is None]
    slips = len(extras) - len(stray)
    denom = total_n + len(stray)
    accuracy = 100.0 * len(hits) / denom if denom else 100.0
    timing = 100.0 * (counts["perfect"] + counts["good"]) / len(hits) if hits else 0.0
    checked = [n for n in hits if n["dur"] >= config.PLAY_SHORT_MIN_BEATS - EPS]
    length = 100.0 * sum(1 for n in checked if not n["short"]) / len(checked) if checked else 100.0
    wa, wt, wl = config.SCORE_WEIGHTS
    total = accuracy * (wa + wt * timing / 100.0 + wl * length / 100.0)
    total = max(0, min(100, int(round(total))))
    stars = 3 if total >= config.STARS[0] else 2 if total >= config.STARS[1] else 1
    errs = [n["err_ms"] for n in hits if n.get("err_ms") is not None]
    return {"total": total, "stars": stars, "accuracy": round(accuracy, 1), "timing": round(timing, 1),
            "length": round(length, 1), "notes": total_n, "hit": len(hits), **counts, "missed": counts["miss"],
            "extra": len(stray), "slips": slips, "short": sum(1 for n in checked if n["short"]),
            "mean_err_ms": round(sum(errs) / len(errs), 1) if errs else None}
