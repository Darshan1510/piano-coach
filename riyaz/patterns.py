"""Left-hand patterns for easy versions (PLAN 8.3 Levels 6 and 8, 8.4, 11.2).

The simplifier (riyaz/simplify.py) makes block chords (one for each group of clicks). From
Level 6 the easy version of an imported song plays them like the built-in "Pop loop" song
(data/songs/pop-loop.json, the "4-chord loop" template of PLAN 8.3): the chord again on the
middle click of a group of 4 (change the chord on time, keep the sound). From Level 8 the left
hand plays a rhythm feel, as in the Level 8 songs:
- 4 clicks (4/4): keherwa - lowest key on 1, the 2 upper keys just after 2, lowest key on 3,
  the 2 upper keys on 4 (aura-lee.json);
- 6 clicks (6/8) and 3 clicks (3/4): dadra - lowest key on 1 and 4, the 2 upper keys on 2 and 5
  (greensleeves.json); in 3/4 one half of it in each group of clicks.
Other time signatures keep the block chords.
"""

from __future__ import annotations

EPS = 1e-6

LOOP_LEVEL = 6  # the loop template (PLAN 8.3 Level 6)
FEEL_LEVEL = 8  # keherwa and dadra (PLAN 8.3 Level 8)

# (offset in clicks, "low" | "up" | "all", length in clicks) for one group of clicks.
KEHERWA = ((0.0, "low", 1.5), (1.5, "up", 0.5), (2.0, "low", 1.0), (3.0, "up", 1.0))
DADRA_6 = ((0.0, "low", 1.0), (1.0, "up", 2.0), (3.0, "low", 1.0), (4.0, "up", 2.0))
DADRA_3 = ((0.0, "low", 1.0), (1.0, "up", 2.0))


def pattern_for(level: int, num: int) -> tuple | None:
    """The pattern of one group of clicks for the level and the time signature (None = block)."""
    if level >= FEEL_LEVEL:
        return {4: KEHERWA, 6: DADRA_6, 3: DADRA_3}.get(num)
    if level >= LOOP_LEVEL and num == 4:
        return ((0.0, "all", 2.0), (2.0, "all", 2.0))
    return None


def apply(lh: list[dict], level: int, num: int) -> list[dict]:
    """Block chords (notes with start, dur, pitch; one chord = the notes with the same start) ->
    the same chords in the pattern. A chord shorter than the pattern part keeps its length."""
    pat = pattern_for(level, num)
    if pat is None:
        return lh
    groups: dict[float, list[dict]] = {}
    for n in lh:
        groups.setdefault(round(n["start"], 6), []).append(n)
    out: list[dict] = []
    for start in sorted(groups):
        chord = sorted(groups[start], key=lambda n: n["pitch"])
        length = max(n["dur"] for n in chord)
        for off, part, dur in pat:
            if off >= length - EPS:
                break
            keys = chord if part == "all" or len(chord) < 2 else chord[:1] if part == "low" else chord[1:]
            for n in keys:
                out.append({**n, "start": round(start + off, 4), "dur": round(min(dur, length - off), 4)})
    return out
