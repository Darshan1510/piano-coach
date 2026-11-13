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
