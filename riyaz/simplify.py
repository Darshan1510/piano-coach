"""Song simplifier (PLAN 11.2) and easy versions by level (PLAN 8.4).

An easy version of a song:

- **Melody** (right hand): the highest note at each time ("skyline") of the right hand (or of all
  notes, when the song has one hand). Very short notes go away; the note before them gets longer.
- **Left hand**: one chord for each group of clicks (bar) or half group, from all notes of the
  song, limited to triads (3 keys). The left hand plays the 3 keys together (a block chord) or
  only the lowest key of the chord (the root).
- Options: melody only, melody + root notes, melody + block chords; move the song to C or G
  (fewer black keys); a slower version (3/4 speed).
- The fingering is made again for the new version (beginner mode where the level allows).

Easy version for a level: the version uses only the skills that the user has (the skill list of
riyaz/difficulty.py). For example Level 1: a right-hand melody in one 5-finger position in C,
white keys only, no pauses. Level 5: the melody + left-hand block chords. The difficulty check
of the new version must give that level or lower; if it does not, the simplifier tries stronger
steps (fewer notes, a smaller range, slower).

A version is a separate song (``source`` "simplified") with ``version_of`` = the source song id,
the level and the options. It is saved in the user songs folder.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from . import config, difficulty, fingering, patterns, songs, theory
from .handsplit import onsets

EPS = 1e-6

LEFT_CHOICES = ("none", "roots", "chords")
KEY_CHOICES = ("same", "C", "G", "auto")
CHANGE_CHOICES = ("bar", "half")
SLOW_FACTOR = 0.75  # the slow version plays at 3/4 of the speed

MIN_NOTE_BEATS = 0.2  # melody notes shorter than this (in beats) are "very short": removed
MIN_NOTE_S = 0.09  # ... or shorter than this in seconds
MELODY_LOW = config.MIDDLE_C  # the melody stays at middle C or higher (the left hand is below)
ROOT_LOW, ROOT_HIGH = 48, 59  # root notes: the octave below middle C
CHORD_ROOT_LOW, CHORD_ROOT_HIGH = 41, 52  # block chords (root position, 7 semitones): below middle C
CHANGED_SHARE = 0.1  # a version with this share of changed tune notes (or more) says so on its card
CHANGED_TEXT = "Some notes are different, so that one hand position plays the song."
FIVE_FINGER_LEVEL = 3  # up to this level: one 5-finger position for each hand, white keys only
WHITE_ONLY_BELOW = difficulty.SKILLS["black_keys"][0]  # black keys are taught at Level 4
LEFT_HAND_LEVEL = difficulty.SKILLS["left_hand"][0]  # Level 3
CHORD_LEVEL = difficulty.SKILLS["keys_together"][0]  # Level 5
PAUSE_LEVEL = difficulty.SKILLS["pauses"][0]  # Level 2
FAST_LEVEL = difficulty.SKILLS["fast_runs"][0]  # Level 7
CROSS_LEVEL = difficulty.SKILLS["thumb_under"][0]  # Level 7
BEGINNER_MAX_LEVEL = 3  # beginner fingering (PLAN 5.3)

# Triad shapes (semitones from the root). Chords with more keys become the triad under them.
TRIADS = {"": (0, 4, 7), "m": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8)}
TRIAD_OF = {"": "", "7": "", "maj7": "", "sus4": "", "m": "m", "m7": "m", "dim": "dim", "aug": "aug"}
_NAME_RE = re.compile(r"^([A-G])([#b]?)(.*)$")
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


class SimplifyError(ValueError):
    """The text is for the user."""


# ------------------------------------------------------------------------------- small helpers


def parse_chord(name: str) -> tuple[int, str] | None:
    """Chord name ("Am7", "Bb", "F#dim") -> (root pitch class, triad suffix). None if unknown."""
    m = _NAME_RE.match(name or "")
    if not m:
        return None
    pc = _PC[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    suffix = TRIAD_OF.get(m.group(3))
    if suffix is None:
        return None
    return pc % 12, suffix


def triad_name(pc: int, suffix: str) -> str:
    return theory.chord_root_name(pc % 12) + suffix


def parse_key(key: str) -> tuple[int, str] | None:
    """Key text ("A minor", "Bb major") -> (tonic pitch class, "major" | "minor")."""
    parts = (key or "").split()
    if len(parts) != 2 or parts[1] not in ("major", "minor"):
        return None
    m = _NAME_RE.match(parts[0])
    if not m or m.group(3):
        return None
    pc = _PC[m.group(1)] + (1 if m.group(2) == "#" else -1 if m.group(2) == "b" else 0)
    return pc % 12, parts[1]


def song_key(song: dict) -> tuple[int, str]:
    k = parse_key(song.get("key", ""))
    if k:
        return k
    cands = theory.key_candidates(song["notes"])
    return (cands[0][1], cands[0][2]) if cands else (0, "major")


def transpose_shift(key: tuple[int, str], target: str) -> int:
    """Semitones (-6..5) that move the song to C or G (A minor / E minor for a minor song)."""
    tonic, mode = key
    want = {"C": 0, "G": 7}[target]
    if mode == "minor":
        want = (want + 9) % 12  # the minor key with the same keys: A minor (C), E minor (G)
    return ((want - tonic + 6) % 12) - 6


def _black_count(pitches, shift: int) -> int:
    return sum(1 for p in pitches if theory.is_black(p + shift))


def _snap_white(pitch: int, prev: int | None) -> int:
    """A black key -> the white key next to it (the one nearer to the note before; else up)."""
    if not theory.is_black(pitch):
        return pitch
    down, up = pitch - 1, pitch + 1
    if prev is not None and abs(prev - down) < abs(prev - up):
        return down
    return up


def _fold(pitch: int, lo: int, hi: int) -> int:
    """Move a note by octaves into [lo, hi] when it fits; else to the nearest end of the range."""
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    if pitch < lo:  # the range is smaller than an octave and the note does not fit
        return pitch if lo - pitch <= (pitch + 12) - hi else pitch + 12
    return pitch


def _strength(beat: float, num: int) -> int:
    """How strong a time in the bar is: 3 = first click of the group, 2 = a click, 1 = half, 0."""
    if abs(beat / num - round(beat / num)) < EPS:
        return 3
    if abs(beat - round(beat)) < EPS:
        return 2
    if abs(beat * 2 - round(beat * 2)) < EPS:
        return 1
    return 0


# ------------------------------------------------------------------------------------ melody


def skyline(song: dict) -> list[dict]:
    """The melody: the highest right-hand note that sounds at each time, one note at a time.

    A start is skipped when a higher note from an earlier start still sounds (a held melody note
    over a moving inner voice); the held note keeps its length. A note ends where the next melody
    note starts. Very short notes are removed and the note before gets their time.
    """
    hands = songs.hands_of(song)
    src = [n for n in song["notes"] if n["hand"] == "R"] if "R" in hands else list(song["notes"])
    melody: list[dict] = []
    for g in onsets(src):
        top = max(g, key=lambda n: n["pitch"])
        if melody:
            last = melody[-1]
            if last["start"] + last["dur"] > top["start"] + EPS and last["pitch"] > top["pitch"]:
                continue  # the higher note before still sounds: it stays the melody
        melody.append(dict(top))
    beat_s = 60.0 / float(song["bpm"])
    for a, b in zip(melody, melody[1:]):
        a["dur"] = min(a["dur"], b["start"] - a["start"])
    out: list[dict] = []
    for n in melody:
        short = n["dur"] < MIN_NOTE_BEATS - EPS or n["dur"] * beat_s < MIN_NOTE_S
        if short and out:
            continue  # the note before gets the time (below)
        out.append(n)
    # A note lasts to the next note when the gap is small (removed notes, or a short gap).
    for a, b in zip(out, out[1:]):
        gap = b["start"] - (a["start"] + a["dur"])
        if gap > EPS and (gap < 0.5 or a["dur"] < MIN_NOTE_BEATS):
            a["dur"] = b["start"] - a["start"]
    return [n for n in out if n["dur"] > EPS]


def thin(melody: list[dict], bpm: float, num: int, min_gap_s: float) -> list[dict]:
    """Remove notes that start less than min_gap_s after the note before (no fast runs).

    The stronger time in the group of clicks wins; the kept note gets the time of the removed note.
    """
    gap_beats = min_gap_s * bpm / 60.0
    out: list[dict] = []
    for n in melody:
        if out and n["start"] - out[-1]["start"] < gap_beats - EPS:
            prev = out[-1]
            if _strength(n["start"], num) > _strength(prev["start"], num) and (
                    len(out) < 2 or n["start"] - out[-2]["start"] >= gap_beats - EPS):
                # the new note is on a stronger time: it replaces the note before
                if len(out) >= 2:
                    out[-2]["dur"] = n["start"] - out[-2]["start"]
                out[-1] = n
            else:
                prev["dur"] = max(prev["dur"], n["start"] + n["dur"] - prev["start"])
            continue
        out.append(n)
    for a, b in zip(out, out[1:]):
        a["dur"] = min(max(a["dur"], EPS), b["start"] - a["start"])
    return out


def legato(notes: list[dict]) -> None:
    """Each note lasts to the start of the next note (no pauses). In place."""
    for a, b in zip(notes, notes[1:]):
        a["dur"] = b["start"] - a["start"]


def best_window(pitches: list[int], hand: str, low: int, high: int) -> int:
    """The thumb (white key) of the 5-finger position that holds most notes (after octave moves)."""
    best = None
    for thumb in range(low, high + 1):
        if theory.is_black(thumb):
            continue
        keys = songs.white_keys_from(thumb, hand)
        pcs = {k % 12 for k in keys}
        hit = sum(1 for p in pitches if p % 12 in pcs)
        center = abs((keys[0] + keys[-1]) / 2 - (67 if hand == "R" else 50))
        score = (hit, -center)
        if best is None or score > best[0]:
            best = (score, thumb)
    return best[1] if best else (60 if hand == "R" else 55)


def into_window(pitch: int, keys: list[int], prev: int | None) -> int:
    """A note -> a key of the 5-finger position: the same note name in that place, else the
    nearest key (the key nearer to the note before when 2 are equally near)."""
    for k in keys:
        if k % 12 == pitch % 12:
            return k
    lo, hi = min(keys), max(keys)
    p = _fold(pitch, lo - 6, hi + 6)
    return min(keys, key=lambda k: (abs(k - p), abs(k - prev) if prev is not None else 0, -k))


def _window_fit(src: dict, shift: int) -> int:
    """How many melody notes keep their note name in the best 5-finger position (after a move)."""
    moved = {**src, "notes": [{**n, "pitch": n["pitch"] + shift} for n in src["notes"]]}
    pitches = [n["pitch"] for n in skyline(moved)]
    keys = songs.white_keys_from(best_window(pitches, "R", 55, 72), "R")
    pcs = {k % 12 for k in keys}
    return sum(1 for p in pitches if p % 12 in pcs)


def changed_text(meta: dict | None) -> str:
    """The card text when many tune notes are different in a version (one hand position)."""
    if not isinstance(meta, dict):
        return ""
    changed, total = meta.get("changed") or 0, meta.get("melody_notes") or 0
    if total and changed >= max(2, CHANGED_SHARE * total):
        return CHANGED_TEXT
    return ""


# ---------------------------------------------------------------------------------- the left hand


def _no_shared_keys(melody: list[dict], lh: list[dict], keep_place: bool) -> list[dict]:
    """No key in both hands at the same time: the left-hand note goes an octave down (or away,
    when the left hand must stay in its 5-finger position)."""
    out = []
    for n in lh:
        def clash(p):
            return any(m["pitch"] == p and m["start"] < n["start"] + n["dur"] - EPS
                       and n["start"] < m["start"] + m["dur"] - EPS for m in melody)
        if clash(n["pitch"]):
            if keep_place or n["pitch"] - 12 < config.KEY_LOW or any(
                    o is not n and o["pitch"] == n["pitch"] - 12 and abs(o["start"] - n["start"]) < EPS for o in lh):
                continue
            n = {**n, "pitch": n["pitch"] - 12}
        out.append(n)
    return out


def chord_plan(song: dict, shift: int, change: str) -> list[dict]:
    """[{start, dur, pc, suffix}] for each group of clicks (or half group), from all notes."""
    num = song["time_signature"][0]
    span = float(num) if change == "bar" or num % 2 else num / 2
    end = song["end"]
    notes = [{**n, "pitch": n["pitch"] + shift} for n in song["notes"]]
    named = theory.chords_for_notes(notes, span, end)
    out: list[dict] = []
    t = 0.0
    last = None
    while t < end - EPS:
        cur = None
        for c in named:  # the chord that sounds at the start of this span
            if c["start"] - EPS <= t < c["start"] + c["dur"] - EPS:
                cur = parse_chord(c["name"])
                break
        if cur is None:
            cur = last
        if cur is not None:
            out.append({"start": t, "dur": min(span, end - t), "pc": cur[0], "suffix": cur[1]})
            last = cur
        t += span
    return out


def _near(pc: int, low: int, high: int, prev: int | None) -> int:
    cands = [p for p in range(low, high + 1) if p % 12 == pc % 12]
    if not cands:
        return low
    return min(cands, key=lambda p: (abs(p - prev) if prev is not None else abs(p - (low + high) / 2), p))


def left_notes(plan: list[dict], mode: str, white_only: bool, window: list[int] | None) -> list[dict]:
    """Left-hand notes from the chord plan: root notes or block chords (root position)."""
    out: list[dict] = []
    prev = None
    for c in plan:
        pcs = [(c["pc"] + i) % 12 for i in TRIADS[c["suffix"]]]
        if mode == "roots":
            if window is not None:
                # One 5-finger position: the root, else another key of the chord in the position.
                inside = [k for k in window if k % 12 in pcs]
                p = next((k for k in inside if k % 12 == pcs[0]), inside[0] if inside else None)
                if p is None:
                    p = into_window(c["pc"] + 48, window, prev)
            else:
                p = _near(c["pc"], ROOT_LOW, ROOT_HIGH, prev)
                if white_only:
                    p = _snap_white(p, prev)
            out.append({"pitch": p, "start": c["start"], "dur": c["dur"], "vel": 64})
            prev = p
        else:
            root = _near(c["pc"], CHORD_ROOT_LOW, CHORD_ROOT_HIGH, prev)
            for i in TRIADS[c["suffix"]]:
                out.append({"pitch": root + i, "start": c["start"], "dur": c["dur"], "vel": 60})
            prev = root
    return out


# ------------------------------------------------------------------------------------ fingering


def position_fingering(line: list[dict], hand: str) -> None:
    """Fingering for one key at a time with no thumb under / finger over: the hand moves.

    Up the keys (right hand) the next finger is the same or higher; down, the same or lower.
    """
    prev = None
    for i, n in enumerate(line):
        if prev is None:
            nxt = line[i + 1]["pitch"] - n["pitch"] if i + 1 < len(line) else 0
            if hand == "L":
                nxt = -nxt
            n["finger"] = 1 if nxt > 0 else 5 if nxt < 0 else 3
        else:
            d = n["pitch"] - prev["pitch"]
            if hand == "L":
                d = -d
            f = prev["finger"]
            if d == 0:
                g = f
            else:
                steps = max(1, round(abs(d) / 2 + 0.01))
                g = max(f, min(5, f + steps)) if d > 0 else min(f, max(1, f - steps))
            n["finger"] = g
        prev = n


def finger_version(song: dict, level: int) -> dict:
    """Fingering for the new version. Beginner mode up to Level 3 (PLAN 5.3); no thumb under or
    finger over below Level 7 (the skill is taught at Level 7)."""
    notes = song["notes"]
    for n in notes:
        n["finger"] = None
    fing = fingering.finger_song(notes, beginner=level <= BEGINNER_MAX_LEVEL)
    song["hand_positions"] = fing["hand_positions"]
    if level < CROSS_LEVEL and difficulty.analyze(song)["stats"].get("crossings"):
        positions = []
        for hand in ("R", "L"):
            mine = sorted((n for n in notes if n["hand"] == hand), key=lambda n: (n["start"], n["pitch"]))
            if not mine:
                continue
            groups = onsets(mine)
            if all(len(g) == 1 for g in groups):
                position_fingering([g[0] for g in groups], hand)
                fing["modes"][hand] = "positions"
            positions += fingering.positions_from_fingers(mine, hand)
        song["hand_positions"] = positions
    return fing["modes"]


# --------------------------------------------------------------------------------------- build


def _options(left: str, key: str, slow: bool, change: str) -> dict:
    if left not in LEFT_CHOICES:
        raise SimplifyError("Select what the left hand plays.")
    if key not in KEY_CHOICES:
        raise SimplifyError("Select No change, To C or To G.")
    if change not in CHANGE_CHOICES:
        raise SimplifyError("Select how often the left hand changes.")
    return {"left": left, "key": key, "slow": bool(slow), "change": change}


def version_id(source_id: str, tag: str) -> str:
    base = source_id if source_id.startswith("my-") else f"my-{source_id}"
    base = base[: 63 - len(tag) - 6].rstrip("-")
    return f"{base}-easy-{tag}"


def make_version(source: dict, left: str = "chords", key: str = "same", slow: bool = False,
                 change: str = "bar", level: int | None = None, _strength_step: int = 0) -> dict:
    """One easy version of a song. ``level`` = the level that the version is for (None = the
    options only, no level rules). Returns a validated song (not saved)."""
    opts = _options(left, key, slow, change)
    src = songs.validate(copy.deepcopy(source)) if "end" not in source else copy.deepcopy(source)
    num = int(src["time_signature"][0])
    rule_level = level if level is not None else 10
    five = rule_level <= FIVE_FINGER_LEVEL
    white_only = rule_level < WHITE_ONLY_BELOW

    # Move the song (transpose) before anything else, so that the chords and keys agree.
    k = song_key(src)
    target = opts["key"]
    if target == "auto":
        pitches = [n["pitch"] for n in src["notes"]]
        sc, sg = transpose_shift(k, "C"), transpose_shift(k, "G")
        target = "C" if _black_count(pitches, sc) <= _black_count(pitches, sg) else "G"
        if five:
            # One hand position: the key where more notes of the tune keep their names wins
            # (octave moves are better than other notes).
            fit = {t: _window_fit(src, transpose_shift(k, t)) for t in ("C", "G")}
            if fit["C"] != fit["G"]:
                target = max(fit, key=fit.get)
    shift = transpose_shift(k, target) if target in ("C", "G") else 0
    new_key = (k[0] + shift) % 12, k[1]

    bpm = float(src["bpm"]) * (SLOW_FACTOR if opts["slow"] else 1.0)
    bpm = round(max(20.0, min(300.0, bpm)), 2)
    if _strength_step >= 2 and not opts["slow"]:
        bpm = round(max(20.0, bpm * SLOW_FACTOR), 2)

    moved = {**src, "notes": [{**n, "pitch": n["pitch"] + shift} for n in src["notes"]]}
    melody = skyline(moved)
    if not melody:
        raise SimplifyError("The song has no notes for the right hand. Select a different song.")
    if rule_level < FAST_LEVEL:
        gap = difficulty.FAST_NOTE_S * (1.1 + 0.4 * _strength_step)
        melody = thin(melody, bpm, num, gap)

    # Melody keys.
    changed = 0  # melody notes with a different note name (not only an octave move)
    window: list[int] | None = None
    if five:
        thumb = best_window([n["pitch"] for n in melody], "R", 55, 72)
        window = songs.white_keys_from(thumb, "R")
        prev = None
        for n in melody:
            p = into_window(n["pitch"], window, prev)
            if p % 12 != n["pitch"] % 12:
                changed += 1
            n["pitch"] = p
            prev = p
    else:
        lo = min(n["pitch"] for n in melody)
        up = 12 * max(0, math.ceil((MELODY_LOW - lo) / 12))
        if max(n["pitch"] for n in melody) + up > config.KEY_HIGH:
            up = 0
        prev = None
        for n in melody:
            p = n["pitch"] + up
            while p < MELODY_LOW:
                p += 12
            while p > config.KEY_HIGH:
                p -= 12
            if white_only:
                p = _snap_white(p, prev)
            if p % 12 != n["pitch"] % 12:
                changed += 1
            n["pitch"] = p
            prev = p
    if rule_level < PAUSE_LEVEL or five:
        legato(melody)
    for n in melody:
        n["hand"] = "R"
        n["vel"] = max(1, min(127, int(n.get("vel", 80))))

    # Left hand.
    mode = opts["left"]
    if level is not None and rule_level < LEFT_HAND_LEVEL:
        mode = "none"
    if level is not None and mode == "chords" and rule_level < CHORD_LEVEL:
        mode = "roots"
    lh: list[dict] = []
    chords: list[dict] = []
    if mode != "none":
        plan = chord_plan(src, shift, opts["change"])
        lwin = None
        if five:
            # The left-hand position is below the right-hand position (no key in both hands).
            roots = [c["pc"] + 48 for c in plan]
            top = min(60, min(window) - 1) if window else 60
            lwin = songs.white_keys_from(best_window(roots, "L", min(50, top), top), "L")
        lh = left_notes(plan, mode, white_only, lwin)
        if level is not None and mode == "chords":  # Levels 6 and 8: the pattern of the level (riyaz/patterns.py)
            lh = patterns.apply(lh, rule_level, num)
        lh = _no_shared_keys(melody, lh, keep_place=lwin is not None)
        for n in lh:
            n["hand"] = "L"
        for c in plan:
            name = triad_name(c["pc"], c["suffix"])
            if chords and chords[-1]["name"] == name and abs(chords[-1]["start"] + chords[-1]["dur"] - c["start"]) < EPS:
                chords[-1]["dur"] += c["dur"]
            else:
                chords.append({"start": c["start"], "dur": c["dur"], "name": name})
        # A key played again at once: the note before ends a little earlier (the key goes up).
        by_key: dict[int, list[dict]] = {}
        for n in lh:
            by_key.setdefault(n["pitch"], []).append(n)
        for lst in by_key.values():
            for a, b in zip(lst, lst[1:]):
                if a["start"] + a["dur"] > b["start"] - EPS:
                    a["dur"] = b["start"] - a["start"]

    notes = sorted(melody + lh, key=lambda n: (n["start"], n["pitch"]))
    for i, n in enumerate(notes):
        n["id"] = i
        n["start"] = round(n["start"], 4)
        n["dur"] = round(max(0.05, n["dur"]), 4)
        n.pop("finger", None)
    song = {
        "id": "x", "title": src["title"], "source": "simplified", "bpm": bpm,
        "time_signature": list(src["time_signature"]), "key": theory.key_name(*new_key),
        "level": 1, "notes": [{"id": n["id"], "pitch": n["pitch"], "start": n["start"], "dur": n["dur"],
                               "hand": n["hand"], "finger": None, "vel": n["vel"]} for n in notes],
        "chords": chords, "sections": copy.deepcopy(src.get("sections") or []),
    }
    for n in song["notes"]:
        if not config.KEY_LOW <= n["pitch"] <= config.KEY_HIGH:
            n["pitch"] = _fold(n["pitch"], config.KEY_LOW, config.KEY_HIGH)
    modes = finger_version(song, rule_level)
    diff = difficulty.analyze(song)
    song["level"] = max(1, min(10, diff["level"]))
    song["difficulty"] = diff
    tag = f"l{level}" if level is not None else hashlib.sha1(json.dumps(opts, sort_keys=True).encode()).hexdigest()[:6]
    song["id"] = version_id(src["id"], tag)
    title = src["title"]
    song["title"] = (f"{title} (easy, Level {level})" if level is not None else f"{title} (easy)")[:80]
    song["version_of"] = {"id": src["id"], "title": title, "level": level, "options": opts,
                          "shift": shift, "fingering": modes, "fits": level is None or song["level"] <= level,
                          "changed": changed, "melody_notes": len(melody)}
    return songs.validate(song)


def for_level(source: dict, level: int) -> dict | None:
    """The easy version of a song for the user's level, or None when the song itself fits.

    The version uses only the skills of that level (PLAN 8.4). The simplifier tries stronger
    steps until the difficulty check gives that level or lower (fewer notes, slower).
    """
    if not 1 <= level <= 10:
        raise SimplifyError("The level must be 1 to 10.")
    src = source
    if int(src.get("level", 1)) <= level and not src.get("version_of"):
        diff = src.get("difficulty") or difficulty.analyze(src)
        if diff["level"] <= level:
            return None
    left = "none" if level < LEFT_HAND_LEVEL else "roots" if level < CHORD_LEVEL else "chords"
    best = None
    for step in range(3):
        v = make_version(src, left=left, key="auto", slow=False, change="bar", level=level, _strength_step=step)
        if best is None or v["level"] < best["level"]:
            best = v
        if v["level"] <= level:
            return v
    return best


def save(song: dict) -> dict:
    """Write the version in the user songs folder. Returns the song. When a different song (for
    example an edited version) has the same id, the new version gets a new id (-2, -3, ...)."""
    song["id"] = songs.free_id(song)
    return songs.save_user_song(song)


def versions_of(all_songs: dict[str, dict]) -> dict[str, list[dict]]:
    """Source song id -> its easy versions."""
    out: dict[str, list[dict]] = {}
    for s in all_songs.values():
        v = s.get("version_of")
        if isinstance(v, dict) and isinstance(v.get("id"), str):
            out.setdefault(v["id"], []).append(s)
    return out


def level_version(all_songs: dict[str, dict], source_id: str, level: int) -> dict | None:
    """The saved easy version of a song for this level (that fits the level), or None."""
    for v in versions_of(all_songs).get(source_id, []):
        meta = v["version_of"]
        if meta.get("level") == level and v["level"] <= level:
            return v
    return None


def needs_version(song: dict, level: int) -> bool:
    """An imported song (not a version) that is too hard for this level."""
    if song.get("source") in ("builtin", "course", "simplified") or song.get("version_of"):
        return False
    diff = song.get("difficulty")
    lvl = diff.get("level") if isinstance(diff, dict) else song.get("level", 1)
    return int(lvl or 1) > level


def ensure_level_version(song: dict, level: int, all_songs: dict[str, dict] | None = None) -> dict | None:
    """Make and save the easy version for this level when the song needs one and it does not
    exist yet. Returns the new version, or None (not needed, exists, or does not fit)."""
    if not needs_version(song, level):
        return None
    all_songs = songs.load_all() if all_songs is None else all_songs
    if level_version(all_songs, song["id"], level) is not None:
        return None
    v = for_level(song, level)
    if v is None or v["level"] > level:
        return None
    return save(v)


def new_versions_after_level_up(level: int) -> list[dict]:
    """After a level-up: a new easy version of each imported song for the new level (PLAN 8.4).
    Returns [{"id", "title", "source_id", "source_title", "text"}]."""
    out = []
    all_songs = songs.load_all()
    for s in list(all_songs.values()):
        try:
            v = ensure_level_version(s, level, all_songs)
        except (SimplifyError, songs.SongError):
            continue
        if v is not None:
            out.append({"id": v["id"], "title": v["title"], "source_id": s["id"], "source_title": s["title"],
                        "text": f"Your song '{s['title']}' has a new version for your level."})
    return out
