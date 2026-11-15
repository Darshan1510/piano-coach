"""Intuition exercises (PLAN 10, Levels 1-8): ear and pattern games on the real keyboard.

The texts are in data/course/intuition.json (term marks, PLAN 7.4). "Find the key" is a drill
(riyaz/drill.py); this module runs the other exercises:

| id          | Level | The app                                   | The user answers                         |
|-------------|-------|-------------------------------------------|------------------------------------------|
| echo        | 2     | plays 3-6 keys (where the hand sits)      | plays the same keys (exact keys)         |
| interval    | 3     | plays 2 keys                              | a button (step, skip, 5th, 8 keys) or plays the 2 keys |
| chord_shape | 5     | names a chord ("D minor")                 | plays its 3 keys together (any octave, any order) |
| major_minor | 5     | plays a chord                             | a button (happy / sad) or plays the same 3 keys |
| next_chord  | 6     | plays 3 chords of a progression and stops | plays the next chord                     |
| find_melody | 7     | plays the start of a known song           | finds it on the keys (any octave); the first key glows |
| add_chords  | 8     | lights the keys of a tune (or the user plays an own tune), finds the key (Krumhansl) and a chord for each group of clicks | plays each chord |
| jam         | 8     | plays a chord loop and the click; the keys of the scale glow | plays any keys; score = % keys from the key family |

A run (``Intuition.start``) has rounds. A round with sound starts in status "listen" (keys are
ignored while the app plays, so the echo of the keyboard speaker and early keys do not count),
then "answer". A wrong answer: one more try; after 2 wrong tries the app shows the answer
(``last`` = "shown") and goes to the next round. Score = rounds right at the first try (find the
tune: keys found at the first try; jam: the share of keys from the key family).

Events: ``intuition`` (the full state after each change). The state has ``solution`` (the keys or
the button of the answer): the page shows it only after a wrong answer or at the end; the fake
player (tools/fake_player.py) reads it.

Sound: the page plays ``play`` (seconds after ``play_at``, server clock) on the Mac (Tone.js).
With ``output: "keyboard"`` the app sends the notes to the keyboard speaker instead; the echo
guard (riyaz/practice.py) drops the notes that come back.
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Callable

from . import clock, config, theory

log = logging.getLogger("riyaz.intuition")
EPS = 1e-6

KINDS = ("echo", "interval", "chord_shape", "major_minor", "next_chord", "find_melody", "add_chords", "jam")
WHITE = (0, 2, 4, 5, 7, 9, 11)
LETTER = {0: "C", 2: "D", 4: "E", 5: "F", 7: "G", 9: "A", 11: "B"}
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)
TRIAD = {"": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6)}

LEAD_S = 0.6  # the first sound of a round starts this long after the round starts
NEXT_S = 1.2  # after a right answer, the next round starts this much later
SHOWN_S = 2.5  # after the app shows the answer
CHORD_WINDOW_S = config.WAIT_CHORD_WINDOW_S  # keys together: down at the same time, or within this
TRIES = 2  # wrong tries before the app shows the answer
TUNE_GAP_S = 2.5  # add_chords: a pause this long after 4 or more keys ends an own tune
JAM_BPM = 90
JAM_BARS = 8
JAM_MIN_KEYS = 8


class IntuitionError(ValueError):
    """The text is for the user."""


# ---------------------------------------------------------------------- music helpers


def triad_pcs(root_pc: int, suffix: str) -> list[int]:
    return [(root_pc + i) % 12 for i in TRIAD[suffix]]


def voicing(root_pc: int, suffix: str, low: int = 43, high: int = 54) -> list[int]:
    """Root position, the root in [low, high] (G2-F#3: the left hand below middle C)."""
    root = next(p for p in range(low, high + 1) if p % 12 == root_pc % 12)
    return [root + i for i in TRIAD[suffix]]


def chord_name(root_pc: int, suffix: str) -> str:
    return theory.chord_root_name(root_pc) + ("m" if suffix == "m" else "dim" if suffix == "dim" else "")


def diatonic(tonic: int, mode: str) -> list[tuple[str, int, str]]:
    """The triads of a key: (roman, root pc, suffix). Minor keys use the major V (harmonic minor)."""
    if mode == "major":
        degrees = (("I", 0, ""), ("ii", 2, "m"), ("iii", 4, "m"), ("IV", 5, ""), ("V", 7, ""), ("vi", 9, "m"))
    else:
        degrees = (("i", 0, "m"), ("III", 3, ""), ("iv", 5, "m"), ("V", 7, ""), ("VI", 8, ""), ("VII", 10, ""))
    return [(r, (tonic + d) % 12, s) for r, d, s in degrees]


# Order of preference when 2 chords fit a part of the tune equally well (the common chords first).
_PREFER = {"I": 0, "i": 0, "V": 1, "IV": 2, "iv": 2, "vi": 3, "VI": 3, "ii": 4, "III": 4, "iii": 5, "VII": 5}


def suggest_chords(segments: list[list[dict]], key: tuple[int, str]) -> list[dict]:
    """A chord of the key for each part of a tune (PLAN 10 "Add chords"): the triad of the key with
    the most tune weight (note length; the first note of the part counts 1.25 times), a little more
    when the chord starts on the first note, the home chord a little more for the last part, and
    the common chords (I, V, IV) a little first."""
    tonic, mode = key
    chords = diatonic(tonic, mode)
    out = []
    for i, seg in enumerate(segments):
        if not seg:
            continue
        w = [0.0] * 12
        for k, n in enumerate(seg):
            w[n["pitch"] % 12] += float(n.get("dur") or 1.0) * (1.25 if k == 0 else 1.0)
        best = None
        for roman, pc, suf in chords:
            score = sum(w[p] for p in triad_pcs(pc, suf))
            if pc == seg[0]["pitch"] % 12:
                score += 0.25
            score -= 0.1 * _PREFER.get(roman, 9)  # the common chords a little first
            if i == len(segments) - 1 and roman in ("I", "i") and score > 0:
                score += 0.5  # end on the home chord
            cand = (-score, _PREFER.get(roman, 9), roman, pc, suf)
            if best is None or cand < best:
                best = cand
        _, _, roman, pc, suf = best
        out.append({"roman": roman, "root": pc, "suffix": suf, "name": chord_name(pc, suf),
                    "pcs": sorted(triad_pcs(pc, suf)), "keys": voicing(pc, suf)})
    return out


def detect_key(notes: list[dict]) -> tuple[int, str]:
    """The key of a short tune: Krumhansl-Schmuckler (theory.key_candidates), but among the keys
    near the best one (correlation within 0.2), a key whose scale has every key of the tune comes
    first. A short tune alone often gives a key that does not have its keys (Ode to Joy, bars
    1-4: E minor 0.57, without F sharp; C major 0.55)."""
    notes = [{"pitch": n["pitch"], "dur": float(n.get("dur") or 1.0)} for n in notes]
    cands = theory.key_candidates(notes)
    if not cands:
        return 0, "major"
    used = {n["pitch"] % 12 for n in notes}
    near = [c for c in cands if c[0] >= cands[0][0] - 0.2]

    def rank(c):
        corr, tonic, mode = c
        fits = used <= set(scale_pcs(tonic, mode)) | ({(tonic + 11) % 12} if mode == "minor" else set())
        return (not fits, -corr)

    best = min(near, key=rank)
    return best[1], best[2]


def scale_pcs(tonic: int, mode: str) -> list[int]:
    return sorted((tonic + d) % 12 for d in (MAJOR_SCALE if mode == "major" else MINOR_SCALE))


def white_step(p: int, n: int) -> int:
    """The white key n white keys up from the white key p."""
    while n > 0:
        p += 1
        if p % 12 in WHITE:
            n -= 1
    return p


# ---------------------------------------------------------------------- rounds


def _seconds(song: dict, beats: float) -> float:
    return beats * 60.0 / float(song.get("bpm") or 90)


def _phrase(song: dict, n_min: int, n_max: int, hand: str = "R", span: int | None = 7,
            rng: random.Random | None = None) -> list[dict]:
    """Notes of one hand, one key at a time, from a song: the first part, or (rng) a random place.
    With span, all keys are within span semitones (where the hand sits)."""
    line = sorted((n for n in song["notes"] if n["hand"] == hand), key=lambda n: (n["start"], -n["pitch"]))
    single, last = [], None
    for n in line:
        if last is not None and abs(n["start"] - last) < EPS:
            continue
        single.append(n)
        last = n["start"]
    if len(single) < n_min:
        return []
    starts = list(range(0, len(single) - n_min + 1))
    if rng is not None:
        rng.shuffle(starts)
    for i in starts:
        out = []
        for n in single[i:i + n_max]:
            ps = [x["pitch"] for x in out] + [n["pitch"]]
            if span is not None and max(ps) - min(ps) > span:
                break
            out.append(n)
        if len(out) >= n_min:
            return out
    return []


def rounds_for(ex: dict, ctx: dict, rng: random.Random) -> list[dict]:
    """The rounds of one run. ctx: {"song": the current song or None, "known": songs that the user
    knows (for "Find the tune" and "Add chords"), "text": render(text, **fields) -> str for the page}."""
    kind = ex["id"]
    n = int(ctx.get("rounds") or ex.get("rounds") or 1)
    text = ctx["text"]
    out: list[dict] = []
    if kind == "echo":
        song = ctx.get("song")
        for i in range(n):
            size = min(6, 3 + i // 2)
            notes = _phrase(song, size, size, rng=rng) if song else []
            if notes:
                keys = [x["pitch"] for x in notes]
            else:  # where the hand sits in Level 1: C D E F G
                keys, p = [], rng.choice([60, 62, 64, 65, 67])
                for _ in range(size):
                    keys.append(p)
                    p = rng.choice([q for q in (60, 62, 64, 65, 67) if abs(q - p) <= 4] or [60])
            out.append({"play": [{"pitch": p, "t": 0.5 * k, "dur": 0.45} for k, p in enumerate(keys)],
                        "prompt": text(ex["prompt"], n=len(keys)),
                        "solution": {"mode": "seq", "keys": [[p] for p in keys], "match": "pitch"}})
    elif kind == "interval":
        choices = ex["choices"]
        for _ in range(n):
            c = rng.choice(choices)
            roots = [p for p in (60, 62, 64, 65, 67, 69) if white_step(p, c["whites"]) - p in
                     {"step": (1, 2), "skip": (3, 4), "fifth": (7,), "octave": (12,)}[c["id"]]]
            root = rng.choice(roots)
            top = white_step(root, c["whites"])
            out.append({"play": [{"pitch": root, "t": 0.0, "dur": 0.7}, {"pitch": top, "t": 0.8, "dur": 0.9}],
                        "prompt": text(ex["prompt"]), "choices": [{"id": x["id"], "label": text(x["label"])} for x in choices],
                        "solution": {"mode": "seq", "keys": [[root], [top]], "match": "pitch", "choice": c["id"]}})
    elif kind == "chord_shape":
        pool = [(0, ""), (7, ""), (5, ""), (9, "m"), (2, "m"), (4, "m"), (2, ""), (9, ""), (4, "")]
        picked = pool[:3] + rng.sample(pool[3:], max(0, n - 3))
        rng.shuffle(picked)
        for pc, suf in picked[:n]:
            key = "prompt_minor" if suf == "m" else "prompt_major"
            out.append({"play": [], "prompt": text(ex[key], root=LETTER[pc]),
                        "solution": {"mode": "set", "pcs": sorted(triad_pcs(pc, suf)), "keys": voicing(pc, suf),
                                     "name": chord_name(pc, suf)}})
    elif kind == "major_minor":
        qs = ["", "m"] * ((n + 1) // 2)
        rng.shuffle(qs)
        for suf in qs[:n]:
            pc = rng.choice((0, 2, 4, 5, 7, 9))
            keys = voicing(pc, suf, 48, 57)
            out.append({"play": [{"pitch": p, "t": 0.0, "dur": 1.4} for p in keys],
                        "prompt": text(ex["prompt"]), "choices": [{"id": x["id"], "label": text(x["label"])} for x in ex["choices"]],
                        "solution": {"mode": "set", "pcs": sorted(triad_pcs(pc, suf)), "keys": keys,
                                     "choice": "minor" if suf == "m" else "major"}})
    elif kind == "next_chord":
        patterns = [("I", "V", "vi", "IV"), ("I", "IV", "V", "I"), ("vi", "IV", "I", "V"), ("I", "vi", "IV", "V")]
        # Each (key, pattern) pair once in a random order (then again, for many rounds).
        pairs: list[tuple[int, tuple]] = []
        while len(pairs) < n:
            more = [(tonic, pat) for tonic in (0, 7, 5) for pat in patterns]
            rng.shuffle(more)
            pairs += more
        for tonic, pat in pairs[:n]:
            table = {r: (pc, s) for r, pc, s in diatonic(tonic, "major")}
            chords = [table[r] for r in pat]
            play = []
            for k, (pc, s) in enumerate(chords[:3]):
                play += [{"pitch": p, "t": 1.1 * k, "dur": 1.0} for p in voicing(pc, s)]
            pc, s = chords[3]
            out.append({"play": play, "prompt": text(ex["prompt"]),
                        "solution": {"mode": "set", "pcs": sorted(triad_pcs(pc, s)), "keys": voicing(pc, s),
                                     "name": chord_name(pc, s), "roman": list(pat)}})
    elif kind == "find_melody":
        known = list(ctx.get("known") or [])
        rng.shuffle(known)
        for song in known[:n]:
            notes = _phrase(song, 4, 7, span=None)
            if not notes:
                continue
            t0 = notes[0]["start"]
            play = [{"pitch": x["pitch"], "t": round(_seconds(song, x["start"] - t0), 3),
                     "dur": round(min(0.9, _seconds(song, x["dur"]) * 0.9), 3)} for x in notes]
            out.append({"play": play, "prompt": text(ex["prompt"], title=song["title"]), "song_id": song["id"],
                        "glow": [notes[0]["pitch"]],
                        "solution": {"mode": "find", "keys": [[x["pitch"]] for x in notes], "match": "pc"}})
    elif kind == "add_chords":
        known = list(ctx.get("known") or [])
        song = rng.choice(known) if known else None
        if song is not None:
            notes = _phrase(song, 6, 12, span=None)
            out.append({"play": [], "phase": "tune", "song_id": song["id"], "prompt": text(ex["prompt"], title=song["title"]),
                        "tune": [{"pitch": x["pitch"], "start": x["start"], "dur": x["dur"]} for x in notes],
                        "bar": float(song["time_signature"][0]),
                        "solution": {"mode": "tune", "keys": [[x["pitch"]] for x in notes], "match": "pitch"}})
    elif kind == "jam":
        key = ctx.get("jam_key") or rng.choice([(0, "major"), (7, "major")])
        tonic, mode = key
        table = {r: (pc, s) for r, pc, s in diatonic(tonic, mode)}
        loop = [table[r] for r in ("I", "V", "vi", "IV")]
        beat = 60.0 / JAM_BPM
        bars = int(ctx.get("bars") or JAM_BARS)
        play, chords, clicks = [], [], []
        for b in range(bars):
            pc, s = loop[b % 4]
            t = b * 4 * beat
            ks = voicing(pc, s, 41, 52)
            play += [{"pitch": p, "t": round(t, 3), "dur": round(4 * beat * 0.95, 3)} for p in ks]
            chords.append({"t": round(t, 3), "name": chord_name(pc, s), "keys": ks})
            clicks += [round(t + k * beat, 3) for k in range(4)]
        scale = scale_pcs(tonic, mode)
        out.append({"play": play, "clicks": clicks, "chords": chords, "length": round(bars * 4 * beat, 3),
                    "prompt": text(ex["prompt"], count=bars),
                    "glow": [p for p in range(53, 85) if p % 12 in scale],
                    "solution": {"mode": "jam", "pcs": scale, "keys": [p for p in range(60, 73) if p % 12 in scale]}})
    return out


# ---------------------------------------------------------------------- the engine


class Intuition:
    """Runs one exercise at a time. MIDI events come from the server sink (after calibration).
    threaded=True: a thread ticks every 5 ms (listen -> answer, the next round, the jam end, the
    keyboard speaker). Tests call tick() with a fake clock."""

    def __init__(self, sink: Callable[[dict], None], now: Callable[[], float] = clock.now, threaded: bool = True):
        self.sink = sink
        self.now = now
        self.threaded = threaded
        self.midi = None  # MidiService (keyboard speaker)
        self.echo = None  # practice.EchoGuard
        self._lock = threading.RLock()
        self.seq = 0
        self.run = 0
        self.spec: dict | None = None
        self.on_done: Callable[[dict, dict], dict | None] | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._reset()

    def _reset(self) -> None:
        self.status = "idle"  # idle | listen | answer | wait | jam | done | stopped
        self.round_i = 0
        self.tries = 0
        self.right = 0  # rounds right at the first try
        self.first: list[bool] = []
        self.last = ""
        self.play_at = 0.0
        self.listen_until = 0.0
        self.next_at: float | None = None
        self.step = 0  # seq / find / tune: the next key
        self.found_first = 0  # find: keys found at the first try
        self.miss_here = 0  # find: wrong keys at this key
        self.round_miss = 0  # find: wrong keys in this round
        self.found_total = 0
        self.down: dict[int, float] = {}
        self.together: dict[int, float] = {}
        self.tune_played: list[dict] = []  # add_chords: the keys of the tune (pitch, t)
        self.tune_last_t: float | None = None
        self.jam_presses = 0
        self.jam_inside = 0
        self.result: dict = {}
        self.output = "mac"
        self._out: list[tuple[float, int, int]] = []  # (time, pitch, velocity) for the keyboard speaker

    # ------------------------------------------------------------------ control

    def start(self, spec: dict, on_done=None, output: str = "mac") -> dict:
        """spec: {"id", "rounds": [...], "skills", "name", "source", "ref"} (riyaz/server.py makes it)."""
        if not isinstance(spec, dict) or spec.get("id") not in KINDS or not spec.get("rounds"):
            raise IntuitionError("The app cannot make this exercise now. Play a song first, then try again.")
        with self._lock:
            self._all_off()
            self._reset()
            self.run += 1
            self.spec = spec
            self.on_done = on_done
            self.output = output if output in ("mac", "keyboard") else "mac"
            self._enter_round(self.now())
            state = self._emit_state()
        self._ensure_thread()
        return state

    def stop(self) -> dict:
        with self._lock:
            if self.status not in ("idle", "done", "stopped"):
                self.status = "stopped"
            self._all_off()
            return self._emit_state()

    def state(self) -> dict:
        with self._lock:
            return self._state(bump=False)

    def replay(self, run: int | None = None) -> dict:
        """Listen again: the app plays the round again (no new try)."""
        with self._lock:
            if run is not None and run != self.run:
                raise IntuitionError("This exercise is not active now.")
            if self.status not in ("answer", "listen") or not self._round().get("play"):
                return self._state(bump=False)
            self._sound(self.now())
            if self._round().get("solution", {}).get("mode") in ("seq",):
                self.step = 0
            self.last = "replay"
            return self._emit_state()

    def answer(self, choice: str, run: int | None = None) -> dict:
        """A button answer (interval, major or minor)."""
        with self._lock:
            if run is not None and run != self.run:
                raise IntuitionError("This exercise is not active now.")
            if self.status not in ("answer", "listen"):
                return self._state(bump=False)
            sol = self._round().get("solution") or {}
            if "choice" not in sol:
                raise IntuitionError("Answer this question on the keyboard.")
            self._judge(choice == sol["choice"], self.now(), choice=choice)
            return self._emit_state()

    def tune_done(self, run: int | None = None) -> dict:
        """add_chords: "My tune is done"."""
        with self._lock:
            if run is not None and run != self.run:
                raise IntuitionError("This exercise is not active now.")
            if self.status == "answer" and self._round().get("phase") == "tune":
                self._finish_tune(self.now())
            return self._emit_state()

    # ------------------------------------------------------------------ rounds

    def _rounds(self) -> list[dict]:
        return self.spec["rounds"] if self.spec else []

    def _round(self) -> dict:
        r = self._rounds()
        return r[self.round_i] if 0 <= self.round_i < len(r) else {}

    def _enter_round(self, t: float) -> None:
        rnd = self._round()
        self.tries = 0
        self.step = 0
        self.miss_here = 0
        self.round_miss = 0
        self.together.clear()
        self.next_at = None
        mode = (rnd.get("solution") or {}).get("mode")
        if mode == "jam":
            self.status = "jam"
            self._sound(t)
            self.listen_until = self.play_at  # keys count from the first chord
            return
        if rnd.get("play"):
            self._sound(t)
            self.status = "listen"
        else:
            self.status = "answer"
            self.play_at = t
            self.listen_until = t

    def _sound(self, t: float) -> None:
        rnd = self._round()
        self.play_at = t + LEAD_S
        end = max((x["t"] + x["dur"] for x in rnd.get("play") or []), default=0.0)
        self.listen_until = self.play_at + (end if rnd.get("solution", {}).get("mode") != "jam" else 0.0)
        if self.output == "keyboard" and self.midi is not None:
            self._all_off()
            for x in rnd.get("play") or []:
                self._out.append((self.play_at + x["t"], x["pitch"], 80))
                self._out.append((self.play_at + x["t"] + x["dur"], x["pitch"], 0))
            self._out.sort()

    def _judge(self, ok: bool, t: float, choice: str | None = None, pitch: int | None = None) -> None:
        sol = self._round().get("solution") or {}
        if ok:
            if self.tries == 0:
                self.right += 1
            self.first.append(self.tries == 0)
            self.last = "right"
            self._after_round(t, NEXT_S)
            return
        self.tries += 1
        self.step = 0
        self.together.clear()
        if self.tries >= TRIES:
            self.first.append(False)
            self.last = "shown"
            self._after_round(t, SHOWN_S)
        else:
            self.last = "wrong"
        if pitch is not None:
            self.sink({"type": "intuition_wrong", "run": self.run, "id": self.spec["id"], "pitch": pitch,
                       "choice": choice, "round": self.round_i})
        elif choice is not None:
            self.sink({"type": "intuition_wrong", "run": self.run, "id": self.spec["id"], "choice": choice,
                       "round": self.round_i, "answer": sol.get("choice") if self.last == "shown" else None})

    def _after_round(self, t: float, gap: float) -> None:
        self.status = "wait"
        self.next_at = t + gap

    def _next(self, t: float) -> None:
        self.round_i += 1
        if self.round_i >= len(self._rounds()):
            self._finish(t)
        else:
            self._enter_round(t)
            self.last = ""

    def _finish(self, t: float) -> None:
        self.status = "done"
        mode = (self._rounds()[0].get("solution") or {}).get("mode") if self._rounds() else None
        res = self.spec.get("results") or {}
        if mode == "jam":
            p, i = self.jam_presses, self.jam_inside
            pct = 100.0 * i / p if p else 0.0
            score = round(pct * min(1.0, p / JAM_MIN_KEYS))
            text = (res.get("jam_few") if p < JAM_MIN_KEYS else res.get("jam")) or ""
            summary = {"score": score, "presses": p, "inside": i, "pct": round(pct, 1),
                       "text": text.format(presses=p, inside=i)}
        elif mode == "find":
            total = max(1, self.found_total)
            score = round(100.0 * self.found_first / total)
            summary = {"score": score, "right": self.found_first, "total": self.found_total,
                       "text": (res.get("melody") or "").format(right=self.found_first, total=self.found_total)}
        else:
            graded = [r for r in self._rounds() if (r.get("solution") or {}).get("mode") != "tune"]
            rounds = max(1, len(graded))
            score = round(100.0 * self.right / rounds)
            summary = {"score": score, "right": self.right, "rounds": len(graded),
                       "text": (res.get("right") or "").format(right=self.right, rounds=len(graded))}
        summary.update(id=self.spec["id"], skills=list(self.spec.get("skills") or []), source=self.spec.get("source"),
                       ref=self.spec.get("ref"), first=list(self.first), key=self.spec.get("key_text"))
        self.result = summary
        if self.on_done is not None:
            try:
                extra = self.on_done(self.spec, summary)
                if extra:
                    self.result = {**summary, **extra}
            except Exception:
                log.exception("The exercise result could not be saved")

    # ------------------------------------------------------------------ MIDI input

    def on_midi(self, evt: dict) -> None:
        kind = evt.get("type")
        if kind not in ("note_on", "note_off"):
            return
        with self._lock:
            if self.spec is None or self.status not in ("listen", "answer", "jam"):
                return
            p = evt["pitch"]
            t = evt.get("t")
            t = self.now() if t is None else t
            if kind == "note_off":
                self.down.pop(p, None)
                return
            self.down[p] = t
            self._tick(t)  # a press just after the sound ends: go to "answer" first
            if self.status == "listen" or t < self.listen_until - EPS and self.status != "jam":
                return  # the app still plays: keys do not count
            sol = self._round().get("solution") or {}
            mode = sol.get("mode")
            changed = True
            if mode == "jam":
                if t < self.play_at - EPS:
                    return
                self.jam_presses += 1
                self.jam_inside += p % 12 in sol["pcs"]
            elif mode == "seq":
                want = sol["keys"][self.step]
                hit = p in want if sol.get("match") == "pitch" else p % 12 in {x % 12 for x in want}
                if hit:
                    self.step += 1
                    if self.step >= len(sol["keys"]):
                        self._judge(True, t)
                    else:
                        self.last = "hit"
                else:
                    self._judge(False, t, pitch=p)
            elif mode == "set":
                want = set(sol["pcs"])
                if p % 12 not in want:
                    self._judge(False, t, pitch=p)
                else:
                    self.together = {q: tq for q, tq in self.together.items()
                                     if q in self.down or t - tq <= CHORD_WINDOW_S + EPS}
                    self.together[p] = t
                    got = {q % 12 for q in self.together}
                    if got >= want:
                        self._judge(True, t)
                    else:
                        self.last = "hit"
            elif mode == "find":
                want = sol["keys"][self.step]
                if p % 12 in {x % 12 for x in want}:
                    self.found_total += 1
                    self.found_first += self.miss_here == 0
                    self.step += 1
                    self.miss_here = 0
                    if self.step >= len(sol["keys"]):
                        if self.round_miss == 0:
                            self.right += 1
                        self.first.append(self.round_miss == 0)  # every key at the first try
                        self.last = "right"
                        self._after_round(t, NEXT_S)
                    else:
                        self.last = "hit"
                else:
                    self.miss_here += 1
                    self.round_miss += 1
                    self.last = "wrong"
                    self.sink({"type": "intuition_wrong", "run": self.run, "id": self.spec["id"], "pitch": p,
                               "round": self.round_i})
            elif mode == "tune":
                self.tune_played.append({"pitch": p, "t": t})
                self.tune_last_t = t
                want = sol["keys"][self.step] if self.step < len(sol["keys"]) else []
                if p in want:
                    self.step += 1
                    self.last = "hit"
                    if self.step >= len(sol["keys"]):
                        self._finish_tune(t)
                else:
                    self.last = "own"  # an own tune: the app follows it
            else:
                changed = False
            if changed:
                self._emit_state()

    # ------------------------------------------------------------------ add chords

    def _finish_tune(self, t: float) -> None:
        rnd = self._round()
        played = self.tune_played
        given = rnd.get("tune") or []
        follows = len(played) >= len(given) > 0 and [x["pitch"] for x in played[-len(given):]] == [x["pitch"] for x in given]
        if follows:
            notes = [dict(x) for x in given]
            bar = float(rnd.get("bar") or 4.0)
            segs: dict[int, list[dict]] = {}
            for x in notes:
                segs.setdefault(int((x["start"] + EPS) // bar), []).append(x)
            segments = [segs[k] for k in sorted(segs)]
        else:
            if len(played) < 4:
                self.last = "short"
                return
            notes = []
            for i, x in enumerate(played):
                nxt = played[i + 1]["t"] if i + 1 < len(played) else x["t"] + 0.5
                notes.append({"pitch": x["pitch"], "dur": max(0.1, min(2.0, nxt - x["t"]))})
            segments = [notes[i:i + 4] for i in range(0, len(notes), 4)]
        key = detect_key(notes)
        chords = suggest_chords(segments, key)
        ex = self.spec.get("texts") or {}
        render = self.spec.get("render") or (lambda s, **kw: s.format(**kw))
        root = theory.chord_root_name(key[0])
        key_text = render(ex.get("key_major" if key[1] == "major" else "key_minor", "{root}"), root=root)
        self.spec["key_text"] = key_text
        self.spec["key"] = {"tonic": key[0], "mode": key[1]}
        new = []
        names_ok = self.spec.get("black_names", True)
        for i, c in enumerate(chords):
            name = c["name"] if names_ok or not any(x in c["name"] for x in "#b") else LETTER.get(c["root"], "")
            new.append({"play": [], "phase": "chord", "prompt": render(ex.get("prompt_chord", ""), key=key_text, i=i + 1,
                                                                        n=len(chords), name=name).replace(" ()", ""),
                        "glow": c["keys"], "chord": c,
                        "solution": {"mode": "set", "pcs": c["pcs"], "keys": c["keys"], "name": c["name"]}})
        self.spec["rounds"] = self._rounds()[: self.round_i + 1] + new
        self.first.append(None)  # the tune round has no right or wrong (one entry for each round)
        self.last = "tune_done"
        self._next(t)

    # ------------------------------------------------------------------ time

    def tick(self, t: float | None = None) -> None:
        with self._lock:
            self._tick(self.now() if t is None else t)

    def _tick(self, t: float) -> None:
        if self.spec is None:
            return
        out = []
        while self._out and self._out[0][0] <= t:
            out.append(self._out.pop(0))
        for _, p, v in out:
            self._send(p, v)
        changed = False
        if self.status == "listen" and t >= self.listen_until - EPS:
            self.status = "answer"
            changed = True
        elif self.status == "wait" and self.next_at is not None and t >= self.next_at - EPS:
            self._next(t)
            changed = True
        elif self.status == "jam" and t >= self.play_at + float(self._round().get("length") or 0) - EPS:
            self._next(t)
            changed = True
        elif (self.status == "answer" and self._round().get("phase") == "tune" and self.tune_last_t is not None
              and len(self.tune_played) >= 4 and self.last == "own" and t - self.tune_last_t >= TUNE_GAP_S):
            self._finish_tune(t)
            changed = True
        if changed:
            self._emit_state()

    def _ensure_thread(self) -> None:
        if not self.threaded or (self._thread is not None and self._thread.is_alive()):
            return
        self._stop.clear()

        def loop():
            while not self._stop.wait(0.005):
                try:
                    self.tick()
                except Exception:
                    log.exception("Intuition tick failed")

        self._thread = threading.Thread(target=loop, name="riyaz-intuition", daemon=True)
        self._thread.start()

    def close(self) -> None:
        with self._lock:
            self._all_off()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    # ------------------------------------------------------------------ keyboard speaker

    def _send(self, pitch: int, vel: int) -> None:
        if self.midi is None:
            return
        try:
            msg = self.midi.note_message(pitch, vel)
            if vel > 0 and self.echo is not None:
                self.echo.sent(msg.note, self.now())  # before the send: the echo can come fast
            self.midi.send(msg)
        except Exception:
            log.exception("Cannot send a note to the keyboard")

    def _all_off(self) -> None:
        offs = {p for _, p, v in self._out if v == 0}
        self._out = []
        for p in offs:
            self._send(p, 0)

    # ------------------------------------------------------------------ state

    def _emit_state(self) -> dict:
        s = self._state()
        self.sink(s)
        return s

    def _state(self, bump: bool = True) -> dict:
        if bump:
            self.seq += 1
        base = {"type": "intuition", "seq": self.seq, "run": self.run, "status": self.status, "t": self.now()}
        if self.spec is None:
            return base
        rnd = self._round()
        sol = rnd.get("solution") or {}
        graded = [r for r in self._rounds() if (r.get("solution") or {}).get("mode") != "tune"]
        base.update(id=self.spec["id"], name=self.spec.get("name"), source=self.spec.get("source"),
                    ref=self.spec.get("ref"), round=self.round_i, rounds=len(self._rounds()),
                    graded_rounds=len(graded), right=self.right, tries=self.tries, last=self.last,
                    prompt=rnd.get("prompt"), choices=rnd.get("choices") or [], play=rnd.get("play") or [],
                    clicks=rnd.get("clicks") or [], chords=rnd.get("chords") or [], length=rnd.get("length"),
                    play_at=self.play_at, listen_until=self.listen_until, phase=rnd.get("phase"),
                    glow=rnd.get("glow") or [], step=self.step, output=self.output, misses=self.miss_here,
                    tune_count=len(self.tune_played) if rnd.get("phase") == "tune" else 0,
                    solution={k: v for k, v in sol.items()}, key_text=self.spec.get("key_text"),
                    jam={"presses": self.jam_presses, "inside": self.jam_inside} if sol.get("mode") == "jam" else None,
                    result=self.result or None)
        return base


# ---------------------------------------------------------------------- content and choice (server, session)


def exercises() -> list[dict]:
    from .course import content

    return content()["intuition"]


def exercise(ex_id: str) -> dict | None:
    from .course import content

    return content()["intuition_by_id"].get(ex_id)


def known_songs(course, level: int) -> list[dict]:
    """Ladder songs that the user knows: played (or done) songs of the open levels; else all
    songs of the open levels. "Find the tune" and "Add chords" use them."""
    from . import course as course_mod

    progress = course.store.song_progress()
    entries = [e for e in course_mod.ladder_entries() if e["level"] <= level]
    played = [e for e in entries if (progress.get(e["song_id"]) or {}).get("runs")]
    out = []
    for e in played or entries:
        s = course_mod.get_song(e["song_id"])
        if s is not None and s not in out:
            out.append(s)
    return out


def make_spec(ex_id: str, course, rng: random.Random, song: dict | None = None, rounds: int | None = None,
              source: str = "intuition", ref=None, bars: int | None = None) -> dict:
    """The rounds of a run, with the texts for this user (locked terms -> plain words)."""
    from .course import content, render_text

    ex = exercise(ex_id)
    if ex is None or ex_id not in KINDS:
        raise IntuitionError("The app does not know this exercise.")
    unlocked = set(course.store.terms())
    level = course.user_level()

    def text(s: str, **kw) -> str:
        return render_text(s.format(**kw) if kw else s, unlocked)

    ctx = {"song": song, "known": known_songs(course, level), "text": text, "rounds": rounds, "bars": bars}
    if ex_id == "jam" and song is not None:
        from .simplify import song_key

        tonic, mode = song_key(song)
        if mode == "minor":
            tonic = (tonic + 3) % 12  # the jam loop is major: the major key with the same keys
        ctx["jam_key"] = (tonic, "major") if tonic in (0, 7, 5, 2) else None
    rs = rounds_for(ex, ctx, rng)
    if "sharp_flat" not in unlocked:  # PLAN 7.4: no black-key names before Level 4 (the keys glow)
        for r in rs:
            for c in r.get("chords") or []:
                if any(x in c["name"] for x in "#b"):
                    c["name"] = ""
    if not rs:
        raise IntuitionError("The app cannot make this exercise now. Play a song first, then try again.")
    res = content()["intuition_results"]
    return {"id": ex_id, "name": text(ex["name"]), "skills": list(ex["skills"]), "rounds": rs,
            "results": {k: render_text(v, unlocked) for k, v in res.items()},
            "texts": {k: ex[k] for k in ("key_major", "key_minor", "prompt_chord") if k in ex},
            "render": text, "source": source, "ref": ref, "song_id": song["id"] if song else None,
            "black_names": "sharp_flat" in unlocked}


def public_list(course) -> list[dict]:
    """The exercises for the Intuition page: names and texts for this user, open or not, the last
    score and the number of runs."""
    from .course import render_text

    unlocked = set(course.store.terms())
    level = course.user_level()
    stats: dict[str, dict] = {}
    for a in course.store.attempts(limit=2000):
        if a["kind"] == "intuition" or (a["kind"] == "drill" and a["item"] == "find_key"):
            item = a["item"]
            st = stats.setdefault(item, {"runs": 0, "last": None, "best": None})
            st["runs"] += 1
            sc = (a["data"] or {}).get("score")
            if a["kind"] == "drill" and sc is None and (a["data"] or {}).get("times"):
                from .review import find_key_score

                sc = find_key_score(a["data"]["times"], int(a["data"].get("wrong") or 0))
            if st["last"] is None and sc is not None:
                st["last"] = sc
            if sc is not None:
                st["best"] = max(st["best"] or 0, sc)
    out = []
    for ex in exercises():
        st = stats.get(ex["id"], {"runs": 0, "last": None, "best": None})
        out.append({"id": ex["id"], "level": ex["level"], "skills": ex["skills"], "open": ex["level"] <= level,
                    "kind": "drill" if ex["id"] == "find_key" else "intuition", "answer": ex.get("answer"),
                    "name": render_text(ex["name"], unlocked), "text": [render_text(x, unlocked) for x in ex["text"]],
                    **st})
    return out


def pick(course, store, level: int, day_seed: int = 0) -> dict:
    """The intuition exercise of the daily session (PLAN 9.1, 9.4): an open exercise for the
    weakest skill. A skill without results counts as the weakest (the user tries a new game).
    Among the exercises of that skill: the one with the fewest runs, then the highest level."""
    from . import skills as skills_mod

    open_ = [e for e in exercises() if e["level"] <= level]
    res = skills_mod.results(store)
    values = {}
    for e in open_:
        for k in e["skills"]:
            if k not in values:
                v = skills_mod._ema(res.get(k) or [])
                values[k] = -1.0 if v is None else v
    focus = min(values, key=lambda k: (values[k], k)) if values else "keys"
    runs: dict[str, int] = {}
    for a in store.attempts(limit=2000):
        if a["kind"] == "intuition" or (a["kind"] == "drill" and a["item"] == "find_key"):
            runs[a["item"]] = runs.get(a["item"], 0) + 1
    cands = [e for e in open_ if focus in e["skills"]] or open_
    best = min(cands, key=lambda e: (runs.get(e["id"], 0), -e["level"], e["id"]))
    return {"exercise": best["id"], "focus": focus, "level": best["level"]}
