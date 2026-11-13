"""Difficulty check for imported songs (PLAN 8.4).

Measures: notes per second, hand span, black keys, keys together (chords), hand moves, both
hands at once, fast runs, pauses. Each measure maps to a skill of the song ladder (PLAN 8.3),
and each skill has the level that teaches it. The song card says if the user can play the song
now, or which skills the song needs and the level that teaches them.

The texts use plain words (PLAN 7.4): "keys together", not "chord"; "pauses", not "rests".
There is no easy version yet (the simplifier is Phase 5), so the card does not offer one
(DECISIONS.md, Phase 3a).
"""

from __future__ import annotations

import bisect

from . import theory
from .handsplit import onsets

# Skill id -> (level that teaches it, plain name for the song card). Order = order on the card.
SKILLS: dict[str, tuple[int, str]] = {
    "right_hand": (1, "the right hand"),
    "small_moves": (1, "small hand moves"),
    "pauses": (2, "pauses"),
    "left_hand": (3, "the left hand"),
    "both_hands": (3, "both hands together"),
    "hand_moves": (4, "hand moves"),
    "black_keys": (4, "black keys"),
    "keys_together": (5, "keys together"),
    "thumb_under": (7, "thumb under or finger over"),
    "fast_runs": (7, "fast runs"),
    "wide_hand": (8, "a wide hand"),
}

FAST_NOTE_S = 0.25  # notes closer than this (at full speed) are fast
FAST_RUN_NOTES = 4  # this many fast notes in a row = a fast run
WIDE_SPAN = 9  # semitones in one hand at once (more than a 5-finger position on white keys)
BIG_MOVE_WHITE_KEYS = 2  # a thumb move of more than this many white keys is a "hand move"
SMALL_MOVES_MAX = 4  # more small moves than this (per hand) also counts as "hand moves"
PAUSE_BEATS = 1.0
CARD_MAX_SKILLS = 4  # the song card names at most this many skills  # a time with no keys of at least this length is a pause


def _white_distance(a: int, b: int) -> int:
    lo, hi = sorted((a, b))
    return sum(1 for p in range(lo, hi) if not theory.is_black(p))


def analyze(song: dict) -> dict:
    """Measures and skills of a song (with fingering and hand positions). JSON-safe."""
    notes = song["notes"]
    bpm = float(song["bpm"])
    beat_s = 60.0 / bpm
    hands = sorted({n["hand"] for n in notes}, key="RL".index)
    stats: dict = {}
    skills: set[str] = set()
    end = max(n["start"] + n["dur"] for n in notes) if notes else 0.0
    seconds = end * beat_s
    stats["seconds"] = round(seconds, 1)
    stats["notes_per_second"] = round(len(notes) / seconds, 2) if seconds > 0 else 0.0
    stats["black_keys"] = sum(1 for n in notes if theory.is_black(n["pitch"]))
    if "R" in hands:
        skills.add("right_hand")
    if "L" in hands:
        skills.add("left_hand")
    if stats["black_keys"]:
        skills.add("black_keys")

    span = 0
    together = 0
    fast_runs = 0
    for hand in hands:
        groups = onsets([n for n in notes if n["hand"] == hand])
        for g in groups:
            span = max(span, g[-1]["pitch"] - g[0]["pitch"])
            if len(g) >= 2:
                together += 1
        run = 1
        for a, b in zip(groups, groups[1:]):
            if (b[0]["start"] - a[0]["start"]) * beat_s < FAST_NOTE_S:
                run += 1
                if run == FAST_RUN_NOTES:
                    fast_runs += 1
            else:
                run = 1
    stats["hand_span"] = span
    stats["keys_together"] = together
    stats["fast_runs"] = fast_runs
    if together:
        skills.add("keys_together")
    if span > WIDE_SPAN:
        skills.add("wide_hand")
    if fast_runs:
        skills.add("fast_runs")

    # Hand moves (from the hand positions of the fingering).
    moves = {"R": 0, "L": 0}
    big = 0
    for hand in hands:
        pos = sorted((p for p in song.get("hand_positions", []) if p["hand"] == hand), key=lambda p: p["start"])
        for a, b in zip(pos, pos[1:]):
            if a["thumb_pitch"] != b["thumb_pitch"]:
                moves[hand] += 1
                if _white_distance(a["thumb_pitch"], b["thumb_pitch"]) > BIG_MOVE_WHITE_KEYS:
                    big += 1
    stats["hand_moves"] = moves["R"] + moves["L"]
    if big or max(moves.values()) > SMALL_MOVES_MAX:
        skills.add("hand_moves")
    elif stats["hand_moves"]:
        skills.add("small_moves")

    # Thumb under / finger over: the fingers cross between 2 notes next to each other.
    crossings = 0
    for hand in hands:
        seq = [g for g in onsets([n for n in notes if n["hand"] == hand]) if len(g) == 1]
        for (a,), (b,) in zip(seq, seq[1:]):
            fa, fb = a.get("finger"), b.get("finger")
            if not fa or not fb or fa == fb or a["pitch"] == b["pitch"]:
                continue
            up = (b["pitch"] > a["pitch"]) == (hand == "R")
            if (up and fb < fa) or (not up and fb > fa):
                crossings += 1
    stats["crossings"] = crossings
    if crossings:
        skills.add("thumb_under")

    # Both hands at once: a note of one hand starts while a note of the other hand sounds.
    both = 0
    if len(hands) == 2:
        left = sorted((n for n in notes if n["hand"] == "L"), key=lambda n: n["start"])
        starts = [n["start"] for n in left]
        max_end: list[float] = []
        for n in left:
            max_end.append(max(max_end[-1] if max_end else 0.0, n["start"] + n["dur"]))
        for n in notes:
            if n["hand"] != "R":
                continue
            i = bisect.bisect_right(starts, n["start"] + 1e-6) - 1
            if i >= 0 and max_end[i] > n["start"] + 1e-6:
                both += 1
    stats["both_hands_notes"] = both
    if both:
        skills.add("both_hands")

    # Pauses: a time with no keys down.
    pauses = 0
    last_end = None
    for n in sorted(notes, key=lambda n: n["start"]):
        if last_end is not None and n["start"] - last_end >= PAUSE_BEATS - 1e-6:
            pauses += 1
        last_end = n["start"] + n["dur"] if last_end is None else max(last_end, n["start"] + n["dur"])
    stats["pauses"] = pauses
    if pauses:
        skills.add("pauses")

    ordered = [s for s in SKILLS if s in skills]
    level = max((SKILLS[s][0] for s in ordered), default=1)
    return {"skills": ordered, "level": level, "stats": stats}


def card_text(difficulty: dict, user_level: int) -> dict:
    """Song card text for the user's level. {"playable": bool, "text": str, "needs": [names]}."""
    skills = [s for s in difficulty.get("skills", []) if s in SKILLS]
    missing = [s for s in skills if SKILLS[s][0] > user_level]
    if not missing:
        return {"playable": True, "needs": [], "level": None, "text": "You can play this song now."}
    names = [SKILLS[s][1] for s in missing]
    level = max(SKILLS[s][0] for s in missing)
    shown = names if len(names) <= CARD_MAX_SKILLS else names[-CARD_MAX_SKILLS:]  # the hardest skills
    more = len(names) - len(shown)
    listed = ", ".join(shown) + (f", and {more} more skill{'s' if more > 1 else ''}" if more else "")
    return {"playable": False, "needs": names, "level": level,
            "text": f"This song needs: {listed}. You learn these in Level {level}."}
