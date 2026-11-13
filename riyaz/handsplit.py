"""Hand split for imported MIDI songs (PLAN 5.2).

- 2 parts (tracks or channels): part 1 = right hand, part 2 = left hand. The user can swap them.
- 1 part (or 3 or more): a dynamic-programming split (Viterbi). The notes that start at the
  same time (an onset) are sorted by pitch; the lower ``s`` notes go to the left hand, the
  others to the right hand. The state is the last place of each hand (mean pitch), so each hand
  stays continuous over time. Cost terms (PLAN 5.2):
    - distance from a moving split point (the middle between the 2 hands; start at middle C),
    - hand span over 1 octave,
    - more than 5 notes at once in one hand,
    - hand jump distance.
"""

from __future__ import annotations

from collections.abc import Iterable

from . import config

EPS = 1e-6

# Cost weights. Tuned on the test files in tests/data/midi (see tests/test_handsplit.py).
W_SPLIT = 0.6  # for each semitone that a note is on the wrong side of the split point
W_SPAN = 4.0  # for each semitone of hand span over 12 (1 octave)
SPAN_MAX = 14  # a hand span over this is not possible
COST_IMPOSSIBLE = 1000.0
W_JUMP = 0.25  # for each semitone that a hand moves from its last place
W_CROSS = 3.0  # for each semitone that the left hand is above the right hand
MAX_STATES = 400

START_L = config.MIDDLE_C - 12  # where the hands start (split point = middle C)
START_R = config.MIDDLE_C + 12


def onsets(notes: Iterable[dict]) -> list[list[dict]]:
    """Group notes that start at the same time. Each group is sorted by pitch."""
    groups: dict[float, list[dict]] = {}
    for n in notes:
        groups.setdefault(round(n["start"], 4), []).append(n)
    return [sorted(groups[k], key=lambda n: n["pitch"]) for k in sorted(groups)]


def split_by_parts(first: list[dict], second: list[dict], swap: bool = False) -> None:
    """2 parts: part 1 = right hand, part 2 = left hand (or the opposite with swap). In place."""
    right, left = (second, first) if swap else (first, second)
    for n in right:
        n["hand"] = "R"
    for n in left:
        n["hand"] = "L"


def _hand_cost(pitches: list[int], last: float, side: str, split: float) -> float:
    if not pitches:
        return 0.0
    cost = 0.0
    span = pitches[-1] - pitches[0]
    if len(pitches) > 5 or span > SPAN_MAX:
        cost += COST_IMPOSSIBLE
    elif span > 12:
        cost += W_SPAN * (span - 12)
    for p in pitches:
        wrong = (p - split) if side == "L" else (split - p)
        if wrong > 0:
            cost += W_SPLIT * wrong
    center = sum(pitches) / len(pitches)
    cost += W_JUMP * abs(center - last)
    return cost


def split_dp(notes: list[dict]) -> None:
    """1 part: set ``hand`` of each note with the dynamic-programming split. In place."""
    groups = onsets(notes)
    # state: (left place, right place) rounded -> (cost, back pointer)
    states: dict[tuple[int, int], tuple[float, int]] = {(START_L, START_R): (0.0, -1)}
    history: list[list[tuple[tuple[int, int], int, int]]] = []  # per onset: (state, prev idx, s)
    prev_keys: list[tuple[int, int]] = [(START_L, START_R)]
    for group in groups:
        pitches = [n["pitch"] for n in group]
        k = len(pitches)
        new: dict[tuple[int, int], tuple[float, int, int]] = {}
        for pi, key in enumerate(prev_keys):
            cost0 = states[key][0]
            lp, rp = key
            split = (lp + rp) / 2
            for s in range(k + 1):
                lo, hi = pitches[:s], pitches[s:]
                c = cost0 + _hand_cost(lo, lp, "L", split) + _hand_cost(hi, rp, "R", split)
                nl = round(sum(lo) / len(lo)) if lo else lp
                nr = round(sum(hi) / len(hi)) if hi else rp
                if nl > nr:
                    c += W_CROSS * (nl - nr)
                nk = (nl, nr)
                if nk not in new or c < new[nk][0]:
                    new[nk] = (c, pi, s)
        best = sorted(new.items(), key=lambda kv: kv[1][0])[:MAX_STATES]
        prev_keys = [kv[0] for kv in best]
        states = {kv[0]: (kv[1][0], kv[1][1]) for kv in best}
        history.append([(kv[0], kv[1][1], kv[1][2]) for kv in best])
    if not history:
        return
    # Back-trace from the best end state (the lists are sorted by cost: index 0 is best).
    idx = 0
    for gi in range(len(groups) - 1, -1, -1):
        _key, prev_idx, s = history[gi][idx]
        for j, n in enumerate(groups[gi]):
            n["hand"] = "L" if j < s else "R"
        idx = prev_idx


def assign_hands(parts: list[list[dict]], swap: bool = False) -> str:
    """Set the hand of each note. Returns the method: "parts" or "split"."""
    if len(parts) == 2 and parts[0] and parts[1]:
        split_by_parts(parts[0], parts[1], swap)
        return "parts"
    merged = [n for p in parts for n in p]
    split_dp(merged)
    if swap:
        for n in merged:
            n["hand"] = "L" if n["hand"] == "R" else "R"
    return "split"
