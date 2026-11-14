"""Spaced repetition (PLAN 9.3), SM-2 style.

Items: the parts (sections) of a learned song, and the "Find the key" drill. A song becomes
"learned" at 100% speed with a play-along score of 85 or more (PLAN 7.3); then each of its parts is
an item, first due 1 day later.

A result counts as a review only when the item is due (day >= due), one time each day:
  score >= 85 -> interval x 2;  60-84 -> same interval;  < 60 -> interval = 1 day.
next due = the review day + interval. Practice before the due day does not change the schedule
(else 5 runs on one day would double the interval 5 times). DECISIONS.md Phase 4.
"""

from __future__ import annotations

import datetime as dt
import time

from . import config
from .db import Store

FIND_KEY = "drill:find_key"


def _add_days(day: str, n: float) -> str:
    return (dt.date.fromisoformat(day) + dt.timedelta(days=max(1, int(round(n))))).isoformat()


def section_item(song_id: str, section: int) -> str:
    return f"section:{song_id}:{section}"


def next_interval(interval: float, score: float) -> float:
    if score >= config.REVIEW_GOOD:
        return interval * 2
    if score >= config.REVIEW_OK:
        return interval
    return 1.0


def add_song(store: Store, song: dict, day: str) -> list[str]:
    """A song is learned: each part becomes an item (first review tomorrow). Returns new items."""
    out = []
    for i, _ in enumerate(song.get("sections") or [{}]):
        item = section_item(song["id"], i)
        if store.review(item) is None:
            store.save_review({"item": item, "kind": "section", "song_id": song["id"], "section": i,
                               "interval_days": float(config.REVIEW_FIRST_DAYS),
                               "due": _add_days(day, config.REVIEW_FIRST_DAYS), "reps": 0, "created": time.time()})
            out.append(item)
    return out


def record(store: Store, item: str, score: float, day: str, kind: str = "section", song_id: str | None = None,
           section: int | None = None, create: bool = False) -> dict | None:
    """A result for an item. Changes the schedule only when the item is due (one time a day)."""
    row = store.review(item)
    if row is None:
        if not create:
            return None
        row = {"item": item, "kind": kind, "song_id": song_id, "section": section,
               "interval_days": float(config.REVIEW_FIRST_DAYS), "due": day, "reps": 0, "created": time.time()}
        interval = float(config.REVIEW_FIRST_DAYS) if score < config.REVIEW_GOOD else float(config.REVIEW_FIRST_DAYS)
    else:
        if day < row["due"] or row.get("last_day") == day:
            return row
        interval = next_interval(float(row["interval_days"]), score)
    row.update(interval_days=interval, due=_add_days(day, interval), reps=int(row.get("reps") or 0) + 1,
               last_score=round(float(score), 1), last_day=day)
    store.save_review(row)
    return row


def record_sections(store: Store, song_id: str, scores: dict, day: str) -> list[dict]:
    out = []
    for k, v in (scores or {}).items():
        r = record(store, section_item(song_id, int(k)), float(v), day)
        if r is not None and r.get("last_day") == day:
            out.append(r)
    return out


def find_key_score(times: list[float], wrong: int) -> int:
    """0-100 from the time to find each key: 2 s or less = 100, 15 points less for each second
    more, 5 points less for each wrong key."""
    if not times:
        return 0
    mean = sum(times) / len(times)
    return int(max(0, min(100, round(100 - max(0.0, mean - 2.0) * 15 - 5 * wrong))))


def due(store: Store, day: str, kind: str | None = None) -> list[dict]:
    """Items due today or earlier, the most overdue first."""
    return [r for r in store.reviews() if r["due"] <= day and (kind is None or r["kind"] == kind)]
