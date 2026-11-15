"""Dynamics coaching (PLAN 3 "Advanced", 8.3 Level 9 "melody louder than LH", Phase 6).

After a play-along run, the app looks at the touch (MIDI velocity) of the keys that the user hit:

- **Balance**: the tune (right hand) must sound louder than the left hand. OK when the mean
  touch of the tune is BALANCE_MIN (share of the user's touch range) or more above the mean touch
  of the left hand. Needs MIN_NOTES hit notes in each hand.
- **Soft and loud parts**: a song part whose notes are soft in the song (mean song velocity of
  SOFT_WANT or lower) must be played soft (mean touch in the lower SOFT_GOT share of the touch
  range); a loud part (LOUD_WANT or higher) must be played loud (LOUD_GOT or higher).

The touch range is the user's softest and loudest key from the setup (step 4), else
DEFAULT_RANGE. When the keys of a run all have about the same touch value (less than SPREAD_MIN
apart: the keyboard has touch response off, or it sends one value), the app gives no tips: the
user cannot change the sound. The server runs this only from FROM_LEVEL or after the SKILL lesson. The texts use no music terms (PLAN 7.4); the server renders them.
"""

from __future__ import annotations

import statistics

DEFAULT_RANGE = (20, 110)
MIN_NOTES = 6  # hit notes with a touch value in each hand (or part)
BALANCE_MIN = 0.08  # the tune is this share of the touch range louder than the left hand, or more
SOFT_WANT, LOUD_WANT = 60, 96  # song velocity: a soft part / a loud part
SOFT_GOT, LOUD_GOT = 0.45, 0.6  # share of the user's touch range
SPREAD_MIN = 4  # touch values of a run less than this apart: touch response is off
FROM_LEVEL = 9  # the course level of the dynamics lessons
SKILL = "melody_louder"

TEXTS = {
    "balance_ok": "Good: the tune sounds louder than the left hand.",
    "balance_low": "Play the tune louder than the left hand. Press the left-hand keys more gently.",
    "soft_ok": "Good: you played {part} softly.",
    "soft_low": "Play {part} softly. Press the keys more gently.",
    "loud_ok": "Good: you played {part} loud.",
    "loud_low": "Play {part} loud. Press the keys harder.",
}


def _range(vel_range) -> tuple[float, float]:
    if vel_range and len(vel_range) == 2 and vel_range[1] > vel_range[0]:
        return float(vel_range[0]), float(vel_range[1])
    return DEFAULT_RANGE


def _norm(v: float, lo: float, hi: float) -> float:
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def analyze(song: dict, log: dict, vel_range=None) -> dict | None:
    """Dynamics of one run (the play-along log). None when the keys had no touch values."""
    notes = [n for n in (log or {}).get("notes") or [] if n.get("grade") not in (None, "miss")
             and isinstance(n.get("vel"), (int, float))]
    if len(notes) < MIN_NOTES:
        return None
    vels = [n["vel"] for n in notes]
    if max(vels) - min(vels) < SPREAD_MIN:
        return None  # one touch value for every key: touch response is off
    lo, hi = _range(vel_range)
    checks: list[dict] = []
    right = [n["vel"] for n in notes if n["hand"] == "R"]
    left = [n["vel"] for n in notes if n["hand"] == "L"]
    balance = None
    if len(right) >= MIN_NOTES and len(left) >= MIN_NOTES:
        mr, ml = statistics.fmean(right), statistics.fmean(left)
        ok = (mr - ml) / (hi - lo) >= BALANCE_MIN - 1e-9
        balance = {"tune": round(mr, 1), "left": round(ml, 1), "ok": ok}
        checks.append({"id": "balance", "ok": ok, "text": TEXTS["balance_ok" if ok else "balance_low"]})
    parts = []
    for i, sec in enumerate(song.get("sections") or []):
        mine = [n for n in notes if sec["start"] - 1e-6 <= n["start"] < sec["end"] - 1e-6 and n.get("want_vel")]
        if len(mine) < MIN_NOTES:
            continue
        want = statistics.fmean(n["want_vel"] for n in mine)
        got = statistics.fmean(_norm(n["vel"], lo, hi) for n in mine)
        if want <= SOFT_WANT:
            kind, ok = "soft", got <= SOFT_GOT + 1e-9
        elif want >= LOUD_WANT:
            kind, ok = "loud", got >= LOUD_GOT - 1e-9
        else:
            continue
        parts.append({"part": i, "name": sec["name"], "want": kind, "got": round(got, 2), "ok": ok})
        checks.append({"id": kind, "ok": ok, "part": i,
                       "text": TEXTS[f"{kind}_{'ok' if ok else 'low'}"].format(part=sec["name"])})
    if not checks:
        return None
    score = int(round(100.0 * sum(1 for c in checks if c["ok"]) / len(checks)))
    tips = [c["text"] for c in checks if not c["ok"]] or [checks[0]["text"]]
    return {"score": score, "balance": balance, "parts": parts, "checks": checks, "tips": tips[:2],
            "range": [lo, hi]}


def all_texts() -> list[str]:
    return [t.format(part="Part 1") for t in TEXTS.values()]
