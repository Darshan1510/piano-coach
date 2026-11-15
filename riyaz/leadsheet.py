"""Lead-sheet mode (PLAN 3 "Advanced", 8.3 Level 10, Phase 6).

The page shows only the tune (the right hand) and the chord names. The user makes the left-hand
part. The app checks the tune like play-along (riyaz/matcher.py) and the left hand on chord-tone
correctness, not on exact notes:

- A key below the split (the lowest key of the tune in the range) is a left-hand key.
- A left-hand key is right when its note name is in the chord that sounds at that time. A key a
  little before a chord change (inside the play-along window) also counts for the next chord.
- Each chord (a chord name with its time) is a "span". The app keeps the different note names
  the user played in each span (a key played again adds nothing).
- A span is "covered" when the user played its root (or its slash bass, "C/E" -> E) or at least
  2 different note names of the chord.
- The credit of a covered span = (right names - wrong names) / right names, not below 0: each
  wrong note name in the span takes away one right name. An uncovered span gives 0.
- Left-hand score = the mean credit of all spans x 100 (no left hand at all = 0). One key played
  again and again, or all keys together, does not give a pass.
- A range with no spans: only the tune counts (``finish`` gives score None).
- Total = LEAD_WEIGHT_TUNE x tune total + LEAD_WEIGHT_LEFT x left-hand score. With a left-hand
  score below LEAD_LEFT_PASS the total stays below the song-done score (config.SONG_DONE_SCORE):
  a good tune with one key held for the whole song (56-60 points on the easy songs) is not done.

The chord names come from the song (``chords``) or, without them, from the song's left-hand
notes (riyaz/theory.chords_for_notes, one name per group of clicks).
"""

from __future__ import annotations

import re

from . import config, theory

EPS = 1e-6
LEAD_WEIGHT_TUNE = 0.6
LEAD_WEIGHT_LEFT = 0.4
LEAD_LEFT_PASS = 70  # a left-hand score below this cannot finish the song

_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NAME_RE = re.compile(r"^([A-G])([#b]?)([^/]*)(?:/([A-G][#b]?))?$")
SHAPES: dict[str, tuple[int, ...]] = {
    "": (0, 4, 7), "m": (0, 3, 7), "7": (0, 4, 7, 10), "m7": (0, 3, 7, 10), "maj7": (0, 4, 7, 11),
    "dim": (0, 3, 6), "aug": (0, 4, 8), "sus4": (0, 5, 7), "sus2": (0, 2, 7), "6": (0, 4, 7, 9),
    "m6": (0, 3, 7, 9), "m7b5": (0, 3, 6, 10), "dim7": (0, 3, 6, 9), "7sus4": (0, 5, 7, 10), "add9": (0, 2, 4, 7),
}


def _pc(letter: str, acc: str) -> int:
    return (_PC[letter] + (1 if acc == "#" else -1 if acc == "b" else 0)) % 12


def parse(name: str) -> tuple[int, str, int | None] | None:
    """Chord name -> (root pitch class, suffix, bass pitch class or None). None if unknown."""
    m = _NAME_RE.match((name or "").strip())
    if not m or m.group(3) not in SHAPES:
        return None
    bass = _pc(m.group(4)[0], m.group(4)[1:]) if m.group(4) else None
    return _pc(m.group(1), m.group(2)), m.group(3), bass


def chord_tones(name: str) -> frozenset[int]:
    """The pitch classes of a chord name ("Am", "G7", "C/E"). Empty for an unknown name."""
    p = parse(name)
    if p is None:
        return frozenset()
    root, suffix, bass = p
    tones = {(root + i) % 12 for i in SHAPES[suffix]}
    if bass is not None:
        tones.add(bass)
    return frozenset(tones)


def chords_of(song: dict) -> list[dict]:
    """The chord names of a song: [{"start", "dur", "name"}] in beats, sorted, only known names."""
    raw = song.get("chords") or []
    if not raw:
        left = [n for n in song["notes"] if n["hand"] == "L"]
        if left:
            bar = float(song["time_signature"][0])
            raw = theory.chords_for_notes(left, bar, float(song["end"]))
    out = [{"start": float(c["start"]), "dur": float(c["dur"]), "name": c["name"]}
           for c in raw if chord_tones(c["name"])]
    return sorted(out, key=lambda c: c["start"])


def melody_split(song: dict, start: float = 0.0, end: float | None = None) -> int | None:
    """The lowest key of the tune (right hand) in the range: a key below it is a left-hand key."""
    end = song["end"] if end is None else end
    tune = [n["pitch"] for n in song["notes"] if n["hand"] == "R" and start - EPS <= n["start"] < end - EPS]
    return min(tune) if tune else None


def sheet(song: dict) -> dict | None:
    """The lead sheet of a song for the page: the chords and the split. None when the song has no
    tune or no chord names."""
    chords = chords_of(song)
    split = melody_split(song)
    if not chords or split is None:
        return None
    return {"chords": chords, "split": split}


class LeadScorer:
    """Scores the user's own left hand against the chord names of one range of the song."""

    def __init__(self, chords: list[dict], split: int, start: float, end: float):
        self.split = int(split)
        self.start, self.end = float(start), float(end)
        self.spans = []
        for c in chords:
            a, b = max(self.start, c["start"]), min(self.end, c["start"] + c["dur"])
            if b - a > EPS:
                p = parse(c["name"])
                anchors = {p[0]} | ({p[2]} if p[2] is not None else set())
                self.spans.append({"start": a, "end": b, "name": c["name"], "tones": chord_tones(c["name"]),
                                   "anchors": frozenset(anchors)})
        self.presses: list[dict] = []

    def is_left(self, pitch: int) -> bool:
        return pitch < self.split

    def _span_at(self, beat: float) -> int | None:
        for i, s in enumerate(self.spans):
            if s["start"] - EPS <= beat < s["end"] - EPS:
                return i
        return None

    def press(self, pitch: int, beat: float, rate: float, vel: int | None = None) -> dict:
        """A left-hand key at song beat `beat`. Returns {"ok", "chord", "span"}."""
        wb = config.PLAY_WINDOW_S * rate
        here = self._span_at(beat)
        ahead = self._span_at(beat + wb)  # a little early for the next chord
        pc = pitch % 12
        span, ok = here, False
        for i in (here, ahead):
            if i is not None and pc in self.spans[i]["tones"]:
                span, ok = i, True
                break
        if span is None:
            span = ahead
        rec = {"beat": round(beat, 4), "pitch": pitch, "ok": ok, "span": span, "vel": vel}
        if span is not None and beat >= self.start - wb - EPS:
            self.presses.append(rec)
        return {"ok": ok, "chord": self.spans[span]["name"] if span is not None else None, "span": span}

    def rewind(self, beat: float) -> None:
        """Play again from `beat` (after "Continue from here"): the keys from there are taken away."""
        self.presses = [p for p in self.presses if p["beat"] < beat - EPS]

    def finish(self) -> dict:
        n_spans = len(self.spans)
        counted = [p for p in self.presses if p["span"] is not None]
        right = [p for p in counted if p["ok"]]
        # Unique (span, note name) pairs: a key played again adds nothing.
        good = {i: set() for i in range(n_spans)}
        bad = {i: set() for i in range(n_spans)}
        for p in counted:
            (good if p["ok"] else bad)[p["span"]].add(p["pitch"] % 12)
        covered, credit = set(), 0.0
        for i, s in enumerate(self.spans):
            if good[i] & s["anchors"] or len(good[i]) >= 2:
                covered.add(i)
                credit += max(0.0, (len(good[i]) - len(bad[i])) / len(good[i]))
        pairs_good = sum(len(v) for v in good.values())
        pairs = pairs_good + sum(len(v) for v in bad.values())
        cover_pct = 100.0 * len(covered) / n_spans if n_spans else 100.0
        tone_pct = 100.0 * pairs_good / pairs if pairs else 0.0
        score = max(0, min(100, int(round(100.0 * credit / n_spans)))) if n_spans else None
        missed = [{"start": s["start"], "name": s["name"]} for i, s in enumerate(self.spans) if i not in covered]
        return {"score": score, "covered": len(covered), "chords": n_spans,
                "cover_pct": round(cover_pct, 1), "tone_pct": round(tone_pct, 1), "keys": len(counted),
                "right_keys": len(right), "missed": missed[:50], "split": self.split, "pass": LEAD_LEFT_PASS}


def combined(tune_total: float, left_score: float | None) -> int:
    """The total of a lead-sheet run (the song-done rule uses it). left_score None (no chord names
    in the range): the tune alone."""
    if left_score is None:
        return max(0, min(100, int(round(tune_total))))
    total = max(0, min(100, int(round(LEAD_WEIGHT_TUNE * tune_total + LEAD_WEIGHT_LEFT * left_score))))
    if left_score < LEAD_LEFT_PASS:
        total = min(total, config.SONG_DONE_SCORE - 1)
    return total
