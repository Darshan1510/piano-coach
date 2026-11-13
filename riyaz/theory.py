"""Minimal music theory for Phase 1: note names and chord names for free play."""

from __future__ import annotations

from collections.abc import Iterable

SHARP_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
BLACK_PCS = frozenset({1, 3, 6, 8, 10})


def pitch_class(pitch: int) -> int:
    return pitch % 12


def is_black(pitch: int) -> bool:
    return pitch_class(pitch) in BLACK_PCS


def note_name(pitch: int, flats: bool = False, octave: bool = False) -> str:
    """Name of a MIDI pitch. Octave numbers use the scientific system (60 = C4)."""
    name = (FLAT_NAMES if flats else SHARP_NAMES)[pitch_class(pitch)]
    if octave:
        name += str(pitch // 12 - 1)
    return name


# (suffix, intervals from the root, quality hint). Order = preference when 2 shapes match.
CHORD_SHAPES: tuple[tuple[str, frozenset[int], str | None], ...] = (
    ("", frozenset({0, 4, 7}), "major"),
    ("m", frozenset({0, 3, 7}), "minor"),
    ("7", frozenset({0, 4, 7, 10}), "major"),
    ("maj7", frozenset({0, 4, 7, 11}), "major"),
    ("m7", frozenset({0, 3, 7, 10}), "minor"),
    ("dim", frozenset({0, 3, 6}), None),
    ("aug", frozenset({0, 4, 8}), None),
    ("sus4", frozenset({0, 5, 7}), None),
    ("sus2", frozenset({0, 2, 7}), None),
    ("6", frozenset({0, 4, 7, 9}), "major"),
    ("m6", frozenset({0, 3, 7, 9}), "minor"),
    ("m7b5", frozenset({0, 3, 6, 10}), None),
    ("dim7", frozenset({0, 3, 6, 9}), None),
    ("7sus4", frozenset({0, 5, 7, 10}), None),
    ("add9", frozenset({0, 2, 4, 7}), "major"),
    # Shapes with no 5th (common in simple left-hand parts).
    ("", frozenset({0, 4}), "major"),
    ("m", frozenset({0, 3}), "minor"),
    ("7", frozenset({0, 4, 10}), "major"),
)

# Roots that use flat names in chord symbols (Bb, Eb, Ab, Db) — the usual pop-chart choice.
_FLAT_ROOTS = frozenset({1, 3, 8, 10})


def chord_root_name(pc: int) -> str:
    return (FLAT_NAMES if pc in _FLAT_ROOTS else SHARP_NAMES)[pc]


def detect_chord(pitches: Iterable[int]) -> dict | None:
    """Name the chord for a set of held keys.

    Returns {"name", "root", "bass", "quality"} or None.
    Needs 3 or more different keys (2 different note names are not enough to be sure).
    """
    ps = sorted(set(pitches))
    if len(ps) < 3:
        return None
    pcs = frozenset(p % 12 for p in ps)
    if len(pcs) < 2:
        return None
    bass = ps[0] % 12
    best: tuple[int, int, str, int, str | None] | None = None
    for rank, (suffix, shape, quality) in enumerate(CHORD_SHAPES):
        for root in pcs:
            if frozenset((p - root) % 12 for p in pcs) != shape:
                continue
            # Prefer the root in the bass, then the earlier shape in the list.
            score = (0 if root == bass else 1, rank)
            if best is None or score < best[:2]:
                best = (score[0], score[1], suffix, root, quality)
    if best is None:
        return None
    _, _, suffix, root, quality = best
    name = chord_root_name(root) + suffix
    if root != bass:
        name += "/" + chord_root_name(bass)
    return {"name": name, "root": chord_root_name(root), "bass": chord_root_name(bass), "quality": quality}


# ---------------------------------------------------------------------------- Phase 3: songs

KEY_NAMES_MAJOR = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
KEY_NAMES_MINOR = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B")

# Krumhansl-Kessler key profiles (Krumhansl 1990), index 0 = the key note.
_KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)


def _pearson(a: list[float], b: tuple[float, ...]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return num / (da * db) if da and db else 0.0


def pitch_class_weights(notes: Iterable[dict]) -> list[float]:
    """Total length (beats) of each pitch class."""
    w = [0.0] * 12
    for n in notes:
        w[n["pitch"] % 12] += float(n["dur"])
    return w


def key_candidates(notes: Iterable[dict]) -> list[tuple[float, int, str]]:
    """All 24 keys, best first: (correlation, tonic pitch class, "major" | "minor").

    Krumhansl-Schmuckler method: correlate the length of each pitch class with the key profiles.
    """
    w = pitch_class_weights(notes)
    if not any(w):
        return []
    out = []
    for tonic in range(12):
        rot = w[tonic:] + w[:tonic]
        out.append((_pearson(rot, _KK_MAJOR), tonic, "major"))
        out.append((_pearson(rot, _KK_MINOR), tonic, "minor"))
    out.sort(key=lambda x: -x[0])
    return out


def key_name(tonic: int, mode: str) -> str:
    names = KEY_NAMES_MAJOR if mode == "major" else KEY_NAMES_MINOR
    return f"{names[tonic % 12]} {mode}"


def detect_key(notes: Iterable[dict]) -> str:
    """Key of a song, for example "C major" or "A minor". Empty text if there are no notes."""
    c = key_candidates(list(notes))
    return key_name(c[0][1], c[0][2]) if c else ""


# Chord shapes for chord names of a song (triads and the common 7th chords). The rank is the
# order of preference when 2 shapes fit equally well.
_SONG_CHORDS: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("", (0, 4, 7)), ("m", (0, 3, 7)), ("7", (0, 4, 7, 10)), ("m7", (0, 3, 7, 10)),
    ("maj7", (0, 4, 7, 11)), ("dim", (0, 3, 6)), ("aug", (0, 4, 8)), ("sus4", (0, 5, 7)),
)


def best_chord(weights: list[float], bass_pc: int | None = None) -> tuple[str, float] | None:
    """The chord name that fits a pitch-class weight list best, and its fit (0-1).

    Fit = weight of the chord notes / all weight, with a small penalty for chord notes that are
    not there and a small bonus when the root is the lowest note. None if there is no weight.
    """
    total = sum(weights)
    if total <= 0:
        return None
    best: tuple[float, int, str] | None = None
    for rank, (suffix, shape) in enumerate(_SONG_CHORDS):
        for root in range(12):
            pcs = [(root + i) % 12 for i in shape]
            inside = sum(weights[p] for p in pcs)
            missing = sum(1 for p in pcs if weights[p] <= 0)
            if weights[root] <= 0:
                continue  # the root must sound
            score = inside / total - 0.20 * missing - 0.10 * (len(shape) - 3) - 0.002 * rank
            if bass_pc is not None and bass_pc == root:
                score += 0.05
            if best is None or score > best[0]:
                best = (score, root, suffix)
    if best is None:
        return None
    score, root, suffix = best
    return chord_root_name(root) + suffix, max(0.0, min(1.0, score))


def chords_for_notes(notes: list[dict], span: float, end: float, min_fit: float = 0.6) -> list[dict]:
    """Chord names for a song: one for each span (a bar), or 2 when the 2 halves differ.

    Returns [{"start", "dur", "name"}] in beats. Chords that are the same as the one before are
    joined. A span with no clear chord gets no entry.
    """
    if span <= 0 or end <= 0:
        return []

    ordered = sorted(notes, key=lambda n: n["start"])
    active: list[dict] = []
    nxt = 0

    def weights(a: float, b: float) -> tuple[list[float], int | None]:
        w = [0.0] * 12
        low = None
        for n in active:
            s, e = n["start"], n["start"] + n["dur"]
            overlap = min(e, b) - max(s, a)
            if overlap > 1e-9:
                w[n["pitch"] % 12] += overlap
                if low is None or n["pitch"] < low:
                    low = n["pitch"]
        return w, (low % 12 if low is not None else None)

    out: list[dict] = []
    t = 0.0
    while t < end - 1e-9:
        b = min(t + span, end)
        # Notes that sound in [t, b): a sweep over the notes sorted by start (fast for long songs).
        while nxt < len(ordered) and ordered[nxt]["start"] < b - 1e-9:
            active.append(ordered[nxt])
            nxt += 1
        active = [n for n in active if n["start"] + n["dur"] > t + 1e-9]
        if not active:
            if nxt >= len(ordered):
                break
            t += span * max(1, int((ordered[nxt]["start"] - t) // span))  # jump over the empty bars
            continue
        whole = best_chord(*weights(t, b))
        mid = t + (b - t) / 2
        first, second = best_chord(*weights(t, mid)), best_chord(*weights(mid, b))
        parts: list[tuple[float, float, str]] = []
        if (first and second and first[0] != second[0] and first[1] >= min_fit + 0.15
                and second[1] >= min_fit + 0.15 and (whole is None or whole[1] < 0.8)):
            parts = [(t, mid - t, first[0]), (mid, b - mid, second[0])]
        elif whole and whole[1] >= min_fit:
            parts = [(t, b - t, whole[0])]
        for s, d, name in parts:
            if out and out[-1]["name"] == name and abs(out[-1]["start"] + out[-1]["dur"] - s) < 1e-6:
                out[-1]["dur"] = round(out[-1]["dur"] + d, 6)
            else:
                out.append({"start": round(s, 6), "dur": round(d, 6), "name": name})
        t = b
    return out
