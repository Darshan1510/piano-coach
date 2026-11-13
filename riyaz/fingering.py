"""Automatic fingering for imported songs (PLAN 5.3).

Dynamic programming (Viterbi) for each hand separately. The notes that start at the same time
(an onset) are one step. The state of a step is the finger set of its notes: one finger (1-5)
for a single note, an ordered finger set for keys together.

Two modes:

- **Beginner mode** (Levels 1-3, PLAN 5.3): fixed 5-finger positions. The state is the hand
  position (thumb on a white key, one finger on each of the next 4 white keys). Each note gets
  the finger that sits on its key. A position change costs a lot, so there are few changes.
  Beginner mode needs white keys only and onsets that fit in one position. If not, the hand
  uses the normal mode.
- **Normal mode**: cost rules after Parncutt, Sloboda, Clarke, Raekallio and Desain (1997),
  "An ergonomic model of keyboard fingering for melodic fragments", and the chord extension of
  Jacobs (2001): comfortable span for each finger pair (MinPrac/MinComf/MinRel/MaxRel/MaxComf/
  MaxPrac), stretch, small and large span, weak fingers, 3 then 4, 4 on a black key after 3,
  thumb on a black key (more in fast passages), 5 on a black key, crossing without the thumb,
  a small penalty for a position change, and no penalty inside a 5-finger position.

Output: ``finger`` for each note, and ``hand_positions`` (thumb pitch and, when the 5 fingers
are not on 5 white keys next to each other, the ``keys`` extension of Phase 2).
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable

from . import config, theory
from .handsplit import onsets
from .songs import white_keys_from

IMPOSSIBLE = 1000.0

# Parncutt et al. (1997), right hand, semitones from the lower finger to the higher finger:
# (MinPrac, MinComf, MinRel, MaxRel, MaxComf, MaxPrac). Negative = the fingers cross.
SPANS: dict[tuple[int, int], tuple[int, int, int, int, int, int]] = {
    (1, 2): (-5, -3, 1, 5, 8, 10),
    (1, 3): (-4, -2, 3, 7, 10, 12),
    (1, 4): (-3, -1, 5, 9, 12, 14),
    (1, 5): (-1, 1, 7, 10, 13, 15),
    (2, 3): (1, 1, 1, 2, 3, 5),
    (2, 4): (1, 1, 3, 4, 5, 7),
    (2, 5): (2, 2, 5, 6, 8, 10),
    (3, 4): (1, 1, 1, 2, 2, 4),
    (3, 5): (1, 1, 3, 4, 5, 7),
    (4, 5): (1, 1, 1, 2, 3, 5),
}

# Beginner mode costs.
B_CHANGE = 6.0  # a hand position change
B_CHANGE_STEP = 1.0  # for each white key that the thumb moves (small moves are better)
B_CHANGE_ON_STEP = 2.0  # a change between 2 notes next to each other (no time to move)
B_REST = 3.0  # the change is cheaper by this when the hand has a pause before the note
B_LOW = 0.02  # for each finger number above 1 (thumb near the lowest note of the position)

# Normal-mode weights (tuned on the built-in songs and the black-key set in tests/data/fingering).
W_FIVE = 1.5  # for each scale step that the 2 fingers are away from a 5-finger position
W_WEAK = 0.1  # weak-finger rule: for each use of finger 4 or 5 (a tie-break; Parncutt uses 1)
W_SAME = 4.0  # the same finger on a new key (single notes)
W_SAME_STEP = 0.5  # ... and for each semitone of the move
W_CHORD_MOVE = 1.0  # keys together after keys together: the same finger on a new key (the hand moves)
W_CHORD_MOVE_STEP = 0.1  # ... and for each semitone of the move
W_CHANGE = 1.0  # a small penalty for a position change
FAST_IOI_BEATS = 0.5  # notes closer than this are a fast passage (thumb on black costs more)


def _x(pitch: int, hand: str) -> int:
    """Pitch as seen from the hand: up for the right hand, down for the left hand (mirror)."""
    return pitch if hand == "R" else -pitch


def _pair_cost(f1: int, x1: int, f2: int, x2: int) -> float:
    """Span costs for 2 fingers on 2 keys (x = mirrored pitch)."""
    if f1 == f2:
        return 0.0 if x1 == x2 else IMPOSSIBLE
    if f1 > f2:
        f1, x1, f2, x2 = f2, x2, f1, x1
    d = x2 - x1
    min_prac, min_comf, min_rel, max_rel, max_comf, max_prac = SPANS[(f1, f2)]
    thumb = f1 == 1
    cost = 0.0
    if d > max_prac:
        cost += 10.0 * (d - max_prac)
    elif d < min_prac:
        cost += 10.0 * (min_prac - d)
    if d > max_comf:  # stretch rule
        cost += 2.0 * (d - max_comf)
    elif d < min_comf:
        cost += 2.0 * (min_comf - d)
    if d < min_rel:  # small-span rule
        cost += (1.0 if thumb else 2.0) * (min_rel - d)
    elif d > max_rel:  # large-span rule
        cost += (1.0 if thumb else 2.0) * (d - max_rel)
    return cost


def _step_cost(f1: int, p1: int, f2: int, p2: int, hand: str, ioi: float, chords: bool = False) -> float:
    """Cost to go from finger f1 on key p1 to finger f2 on key p2 (Parncutt rules).

    chords=True: both onsets have keys together. Then the same finger on a new key is a hand
    move (normal for a chord change), not a same-finger legato.
    """
    x1, x2 = _x(p1, hand), _x(p2, hand)
    if f1 == f2:
        if p1 == p2:
            return 0.0
        if chords:
            return W_CHORD_MOVE + W_CHORD_MOVE_STEP * abs(p2 - p1)
        return W_SAME + W_SAME_STEP * abs(p2 - p1)  # same finger on a new key
    cost = _pair_cost(f1, x1, f2, x2)
    b1, b2 = theory.is_black(p1), theory.is_black(p2)
    lo, hi = (f1, f2) if f1 < f2 else (f2, f1)
    d = (x2 - x1) if f1 < f2 else (x1 - x2)
    if d < 0:  # the fingers cross
        if lo != 1:
            cost += 8.0  # crossing without the thumb
        else:
            cost += 1.0  # thumb passing
            thumb_black = b2 if f2 == 1 else b1
            if thumb_black:
                cost += 2.0
    if f1 == 3 and f2 == 4:
        cost += 1.0  # three-to-four rule
        if not b1 and b2:
            cost += 1.0  # four-on-black rule
    if f2 == 1 and b2:  # thumb-on-black rule
        cost += 1.0 + (2.0 if not b1 else 0.0) + (1.0 if ioi < FAST_IOI_BEATS else 0.0)
    if f1 == 1 and b1 and not b2:
        cost += 2.0
    if f2 == 5 and b2 and not b1:
        cost += 2.0  # five-on-black rule
    if f1 == 5 and b1 and not b2:
        cost += 2.0
    if hi in (4, 5) and lo != 1 and abs(d) > 3:
        cost += 0.5
    min_comf, max_comf = SPANS[(lo, hi)][1], SPANS[(lo, hi)][4]
    if d > max_comf or d < min_comf:
        cost += W_CHANGE  # small penalty for a position change
    elif d >= 0:
        # Reward for a 5-finger position: one finger on each scale step (a cost when not so).
        cost += W_FIVE * abs(_steps(min(p1, p2), max(p1, p2)) - (hi - lo))
    return cost


def _white_steps(a: int, b: int) -> int:
    """White keys from a (not counted) up to b (counted)."""
    return sum(1 for p in range(a + 1, b + 1) if not theory.is_black(p))


def _steps(a: int, b: int) -> int:
    """Scale steps from a up to b: white keys when both are white, else about 7/12 of the semitones.

    So a black key next to a white key (A to B flat) is one step, as in a scale.
    """
    if not theory.is_black(a) and not theory.is_black(b):
        return _white_steps(a, b)
    return max(1, round((b - a) * 7 / 12)) if b > a else 0


def _chord_cost(fingers: tuple[int, ...], pitches: list[int], hand: str) -> float:
    """Keys together: span cost for each pair of fingers next to each other (Jacobs 2001)."""
    cost = 0.0
    for (fa, pa), (fb, pb) in itertools.pairwise(zip(fingers, pitches)):
        xa, xb = _x(pa, hand), _x(pb, hand)
        lo, hi, d = (fa, fb, xb - xa) if fa < fb else (fb, fa, xa - xb)
        if d < hi - lo:
            return IMPOSSIBLE  # no room for the fingers between them
        min_prac, _mc, _mr, max_rel, max_comf, max_prac = SPANS[(lo, hi)]
        if d > max_prac or d < min_prac:
            return IMPOSSIBLE
        if d > max_comf:
            cost += 2.0 * (d - max_comf)
        if d > max_rel:
            cost += 0.5 * (d - max_rel)
        cost += W_FIVE * abs(_steps(min(pa, pb), max(pa, pb)) - (hi - lo))  # 5-finger position
    return cost


def _weak(fingers: Iterable[int]) -> float:
    return sum(W_WEAK for f in fingers if f in (4, 5))  # weak-finger rule (smaller than Parncutt)


def _states(pitches: list[int], hand: str) -> list[tuple[int, ...]]:
    """Finger sets for the keys of one onset (pitches sorted up). Fingers follow the mirrored order."""
    k = len(pitches)
    if k > 5:
        return []
    combos = list(itertools.combinations(range(1, 6), k))
    return combos if hand == "R" else [tuple(reversed(c)) for c in combos]


def finger_normal(groups: list[list[dict]], hand: str) -> None:
    """Normal mode (Parncutt rules). Sets ``finger`` in place."""
    if not groups:
        return
    layers: list[list[tuple[tuple[int, ...], float, int]]] = []  # (fingers, cost, back pointer)
    prev: list[tuple[tuple[int, ...], float, int]] | None = None
    prev_group: list[dict] | None = None
    for group in groups:
        pitches = [n["pitch"] for n in group]
        layer = []
        for fs in _states(pitches, hand):
            emit = _chord_cost(fs, pitches, hand) + _weak(fs)
            if emit >= IMPOSSIBLE:
                continue
            if prev is None:
                layer.append((fs, emit, -1))
                continue
            ioi = group[0]["start"] - prev_group[0]["start"]
            chords = len(group) > 1 and len(prev_group) > 1
            best_c, best_i = None, -1
            for i, (pfs, pc, _b) in enumerate(prev):
                trans = 0.0
                for f, p in zip(fs, pitches):
                    # Pair each key with the same finger before (if any), else with the nearest key.
                    if f in pfs:
                        pp = prev_group[pfs.index(f)]["pitch"]
                        trans += _step_cost(f, pp, f, p, hand, ioi, chords)
                    else:
                        j = min(range(len(pfs)), key=lambda j: abs(prev_group[j]["pitch"] - p))
                        trans += _step_cost(pfs[j], prev_group[j]["pitch"], f, p, hand, ioi, chords)
                trans /= len(fs)
                c = pc + trans
                if best_c is None or c < best_c:
                    best_c, best_i = c, i
            layer.append((fs, best_c + emit, best_i))
        if not layer:  # cannot finger this onset (should not happen with <= 5 keys): keep order
            fs = tuple(range(1, len(pitches) + 1))[:5]
            layer = [(fs if hand == "R" else tuple(reversed(fs)), (prev[0][1] if prev else 0.0) + 50, 0)]
        layers.append(layer)
        prev, prev_group = layer, group
    i = min(range(len(layers[-1])), key=lambda i: layers[-1][i][1])
    for gi in range(len(groups) - 1, -1, -1):
        fs, _c, back = layers[gi][i]
        for n, f in zip(groups[gi], fs):
            n["finger"] = f
        i = back


def _window(thumb: int, hand: str) -> list[int]:
    return white_keys_from(thumb, hand)


def finger_beginner(groups: list[list[dict]], hand: str) -> bool:
    """Beginner mode: fixed 5-finger positions on white keys. False if the notes do not fit."""
    if not groups:
        return True
    if any(theory.is_black(n["pitch"]) for g in groups for n in g):
        return False
    lo = min(n["pitch"] for g in groups for n in g)
    hi = max(n["pitch"] for g in groups for n in g)
    thumbs = [t for t in range(max(config.KEY_LOW, lo - 9), min(config.KEY_HIGH, hi + 9) + 1)
              if not theory.is_black(t)]
    windows = {t: _window(t, hand) for t in thumbs}
    layers: list[dict[int, tuple[float, int | None]]] = []
    prev: dict[int, tuple[float, int | None]] | None = None
    prev_group: list[dict] | None = None
    for group in groups:
        layer: dict[int, tuple[float, int | None]] = {}
        for t, keys in windows.items():
            if not all(n["pitch"] in keys for n in group):
                continue
            emit = B_LOW * sum(keys.index(n["pitch"]) for n in group)
            if prev is None:
                layer[t] = (emit, None)
                continue
            gap = group[0]["start"] - max(n["start"] + n["dur"] for n in prev_group)
            step = abs(group[0]["pitch"] - prev_group[-1]["pitch"]) <= 2
            best_c, best_t = None, None
            for pt, (pc, _b) in prev.items():
                if pt == t:
                    c = pc
                else:
                    moved = abs(sum(1 for k in range(min(pt, t), max(pt, t)) if not theory.is_black(k)))
                    c = pc + B_CHANGE + B_CHANGE_STEP * moved + (B_CHANGE_ON_STEP if step else 0.0)
                    if gap > 0.25:
                        c -= B_REST
                if best_c is None or c < best_c:
                    best_c, best_t = c, pt
            layer[t] = (best_c + emit, best_t)
        if not layer:
            return False  # this onset does not fit in one 5-finger position
        layers.append(layer)
        prev, prev_group = layer, group
    t = min(layers[-1], key=lambda k: layers[-1][k][0])
    for gi in range(len(groups) - 1, -1, -1):
        keys = windows[t]
        for n in groups[gi]:
            n["finger"] = keys.index(n["pitch"]) + 1
        t = layers[gi][t][1]
    return True


def positions_from_fingers(notes: list[dict], hand: str) -> list[dict]:
    """Hand positions (PLAN 5.1 ``hand_positions``) from the fingering of one hand.

    A new position starts at an onset when a finger is not on the key of the position before.
    The new position keeps the keys of the fingers that do not play, when they still fit.
    """
    out: list[dict] = []
    frame: list[int] | None = None  # mirrored x of fingers 1-5 (strictly up)
    for group in onsets(notes):
        want = {n["finger"]: _x(n["pitch"], hand) for n in group if n.get("finger")}
        if not want:
            continue
        if frame is not None and all(frame[f - 1] == x for f, x in want.items()):
            continue
        new = _build_frame(want, frame, hand)
        if any(b <= a for a, b in itertools.pairwise(new)):
            new = _build_frame(want, None, hand)
        frame = new
        keys = [_x_to_pitch(x, hand) for x in frame]
        pos = {"hand": hand, "start": group[0]["start"], "thumb_pitch": keys[0]}
        if keys != white_keys_from(keys[0], hand):
            pos["keys"] = keys
        out.append(pos)
    return out


def _x_to_pitch(x: int, hand: str) -> int:
    return x if hand == "R" else -x


def _white_step(x: int, hand: str, direction: int) -> int:
    """Next white key from x (mirrored), in the direction +1 (away from the thumb) or -1."""
    p = _x_to_pitch(x, hand)
    step = direction if hand == "R" else -direction
    p += step
    while theory.is_black(p):
        p += step
    return _x(p, hand)


def _build_frame(want: dict[int, int], old: list[int] | None, hand: str) -> list[int]:
    frame: list[int | None] = [None] * 5
    for f, x in want.items():
        frame[f - 1] = x
    known = sorted(want)
    # Keep the old keys that still fit between the known fingers.
    if old is not None:
        for i in range(5):
            if frame[i] is not None:
                continue
            below = [frame[j] for j in range(i) if frame[j] is not None]
            above = [frame[j] for j in range(i + 1, 5) if frame[j] is not None]
            lo_ok = not below or old[i] > max(below) + (i - max(j for j in range(i) if frame[j] is not None) - 1)
            hi_ok = not above or old[i] < min(above) - (min(j for j in range(i + 1, 5) if frame[j] is not None) - i - 1)
            if lo_ok and hi_ok and abs(old[i] - frame[known[0] - 1]) <= 14:
                frame[i] = old[i]
    # Fill the rest with white keys, out from the known fingers (by semitone when no room).
    for i in range(5):
        if frame[i] is not None:
            continue
        left = max((j for j in range(i) if frame[j] is not None), default=None)
        right = min((j for j in range(i + 1, 5) if frame[j] is not None), default=None)
        if left is not None:
            x = _white_step(frame[left], hand, +1)
            for _ in range(i - left - 1):
                x = _white_step(x, hand, +1)
            if right is not None and x > frame[right] - (right - i):
                x = frame[left] + (i - left)  # no room for white keys: next keys by semitone
            frame[i] = x
        else:
            x = _white_step(frame[right], hand, -1)
            for _ in range(right - i - 1):
                x = _white_step(x, hand, -1)
            frame[i] = x
    return [int(x) for x in frame]  # type: ignore[arg-type]


def finger_song(notes: list[dict], beginner: bool = True) -> dict:
    """Finger all notes (both hands) and return {"hand_positions", "modes"}. Sets ``finger``.

    beginner=True tries beginner mode first for each hand (Levels 1-3).
    """
    positions: list[dict] = []
    modes: dict[str, str] = {}
    for hand in ("R", "L"):
        mine = [n for n in notes if n["hand"] == hand]
        if not mine:
            continue
        groups = onsets(mine)
        groups = [g[:5] for g in groups]  # the importer keeps at most 5 keys at once in one hand
        ok = beginner and finger_beginner(groups, hand)
        if not ok:
            finger_normal(groups, hand)
        modes[hand] = "beginner" if ok else "normal"
        positions += positions_from_fingers([n for g in groups for n in g], hand)
    return {"hand_positions": positions, "modes": modes}

