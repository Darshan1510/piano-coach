"""Skill model (PLAN 9.4): a 0-100 level for each skill, from the scores of the related exercises.

Each skill takes the newest SKILL_HISTORY related results (oldest first) and makes a moving
average (newer results count more, SKILL_ALPHA). A skill without results has no level (None).

| Skill          | Results                                                                 |
|----------------|-------------------------------------------------------------------------|
| keys           | wait mode: % of keys right the first time; play-along accuracy; "Find the key" |
| rhythm         | play-along timing % (perfect + good)                                    |
| right / left   | % of the notes of that hand that the user played (play-along, wait mode) |
| coordination   | play-along total score of runs with both hands                          |
| chords         | % of keys-together places with all keys (play-along)                    |
| scales, ear    | no exercises in this version (Phase 5)                                  |

The weakest skill picks the warm-up and the intuition exercise (riyaz/session.py).
"""

from __future__ import annotations

from . import config
from .db import Store

# Names use term marks (PLAN 7.4): a locked term shows its plain word.
SKILLS = (
    ("keys", "Find the keys"),
    ("rhythm", "Timing"),
    ("right", "Right hand"),
    ("left", "Left hand"),
    ("coordination", "Both hands together"),
    ("chords", "[[chord|Chords|Keys together]]"),
    ("scales", "[[scale|Scales|8-key walks]]"),
    ("ear", "Play by ear"),
)


def _ema(values: list[float]) -> float | None:
    if not values:
        return None
    v = values[0]
    for x in values[1:]:
        v = config.SKILL_ALPHA * x + (1 - config.SKILL_ALPHA) * v
    return round(max(0.0, min(100.0, v)), 1)


def results(store: Store, limit: int = 1000) -> dict[str, list[float]]:
    """Related results for each skill, oldest first."""
    from .review import find_key_score

    out: dict[str, list[float]] = {k: [] for k, _ in SKILLS}
    for a in reversed(store.attempts(limit=limit)):
        d = a["data"] or {}
        hands = set(a["hands"] or "")
        if a["kind"] == "song" and a["completed"] and a["accuracy"] is not None:
            mode = d.get("mode", "wait")
            if mode == "play" and isinstance(d.get("score"), dict):
                sc = d["score"]
                out["keys"].append(float(sc.get("accuracy") or 0))
                if sc.get("hit"):
                    out["rhythm"].append(float(sc.get("timing") or 0))
                for h, k in (("R", "right"), ("L", "left")):
                    v = (d.get("hand_acc") or {}).get(h)
                    if v is not None:
                        out[k].append(float(v))
                if hands >= {"R", "L"}:
                    out["coordination"].append(float(sc.get("total") or 0))
                if d.get("groups_pct") is not None:
                    out["chords"].append(float(d["groups_pct"]))
            elif mode == "wait":
                out["keys"].append(float(a["accuracy"]))
                for h, k in (("R", "right"), ("L", "left")):
                    if hands == {h}:
                        out[k].append(float(a["accuracy"]))
        elif a["kind"] == "drill" and a["item"] == "find_key" and d.get("times"):
            out["keys"].append(float(find_key_score(d["times"], int(d.get("wrong") or 0))))
    return {k: v[-config.SKILL_HISTORY:] for k, v in out.items()}


def model(store: Store, unlocked=()) -> list[dict]:
    from .course import render_text

    res = results(store)
    return [{"id": k, "name": render_text(name, set(unlocked)), "value": _ema(res[k]), "n": len(res[k])}
            for k, name in SKILLS]


def weakest(store: Store, choices: list[str]) -> str | None:
    """The weakest skill (lowest level) among choices that have results. None without results."""
    res = results(store)
    vals = [(_ema(res[k]), k) for k in choices if res.get(k)]
    return min(vals)[1] if vals else None
