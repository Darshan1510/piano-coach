"""Daily session, practice time, streak and reminder (PLAN 9.1, 9.2).

Daily session (default 20 minutes; 10, 15, 20 or 30): 4 blocks.
- Warm-up 10%: a short pattern from the current song (its hardest part, else its first hand move,
  else its first notes), slowly, 3 times (a drill).
- Song 60%: the current ladder song (or the imported song that the user selected). The hardest
  part first (from the error data, if there is any), then the whole song. Skill moments come
  inside the song (riyaz/practice.py breaks).
- Review 15%: the spaced-repetition item that is due (riyaz/review.py), played along. Without a due
  item: one part of a done song (the song played least recently; its part with the most errors).
  Without a done song: a part of the current song.
- Intuition 15%: the exercises of PLAN 10 are Phase 5. For now: "Find the key" (Level 1+).
- The weakest skill (riyaz/skills.py) picks the hands of the warm-up and the focus of the
  intuition exercise (Phase 4 has one exercise: "Find the key").

Practice time: the time between 2 key presses counts when it is shorter than ACTIVITY_GAP_S.
A day counts for the streak with PRACTICE_DAY_SECONDS of practice or a finished session.
Streak freeze: one missed day in each week (Monday-Sunday) does not break the streak.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import subprocess
import threading
import time
from collections.abc import Callable

from . import config, review, skills, songs
from .course import Course, get_song, ladder_entry, today
from .db import Store

log = logging.getLogger("riyaz.session")
EPS = 1e-6


class SessionError(ValueError):
    """The text is for the user."""


# ---------------------------------------------------------------------- habit settings


def habit_settings(store: Store) -> dict:
    saved = store.get("habit", None)
    saved = saved if isinstance(saved, dict) else {}
    minutes = saved.get("session_minutes")
    goal = saved.get("goal_minutes")
    t = saved.get("notify_time")
    return {
        "session_minutes": minutes if minutes in config.SESSION_MINUTES else config.SESSION_MINUTES_DEFAULT,
        "goal_minutes": goal if goal in config.GOAL_MINUTES else config.GOAL_MINUTES_DEFAULT,
        "notify": saved.get("notify") is True,
        "notify_time": t if isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) else config.NOTIFY_TIME_DEFAULT,
        "song_id": saved.get("song_id") if isinstance(saved.get("song_id"), str) else None,
    }


def set_habit_settings(store: Store, body: dict) -> dict:
    cur = habit_settings(store)
    if body.get("session_minutes") in config.SESSION_MINUTES:
        cur["session_minutes"] = body["session_minutes"]
    if body.get("goal_minutes") in config.GOAL_MINUTES:
        cur["goal_minutes"] = body["goal_minutes"]
    if isinstance(body.get("notify"), bool):
        cur["notify"] = body["notify"]
    t = body.get("notify_time")
    if isinstance(t, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
        cur["notify_time"] = t
    if "song_id" in body:
        sid = body["song_id"]
        cur["song_id"] = sid if isinstance(sid, str) and songs.get(sid) is not None else None
    store.set("habit", cur)
    return cur


# ---------------------------------------------------------------------- practice time


class Activity:
    """Practice time from key presses. Thread-safe (the MIDI thread calls press())."""

    def __init__(self, store: Store, now: Callable[[], float] = time.time,
                 day: Callable[[], str] = today, gap: float = config.ACTIVITY_GAP_S):
        self.store = store
        self.now = now
        self.day = day
        self.gap = gap
        self._lock = threading.Lock()
        self._last: float | None = None
        self._pending = 0.0
        self._pending_day: str | None = None
        self._flushed = now()
        self.session_id: int | None = None
        self.session_day: str | None = None  # practice time of a different day does not go to the session
        self._boundary: float | None = None  # time of the last set_session(): a gap over it is split

    def press(self, t: float | None = None) -> None:
        t = self.now() if t is None else t
        with self._lock:
            day = self.day()
            if self._pending_day is not None and day != self._pending_day:
                self._flush()
            if self._last is not None and 0 < t - self._last < self.gap:
                b = self._boundary
                if b is not None and self._last < b < t:
                    # The gap started before the session changed: that part is for the day only.
                    self.store.add_seconds(day, b - self._last, None)
                    self._pending += t - b
                else:
                    self._pending += t - self._last
                self._pending_day = day
            self._last = t
            if t - self._flushed >= config.ACTIVITY_FLUSH_S:
                self._flush()

    def flush(self) -> None:
        with self._lock:
            self._flush()

    def _flush(self) -> None:
        if self._pending > 0 and self._pending_day:
            sid = self.session_id if self.session_day in (None, self._pending_day) else None
            self.store.add_seconds(self._pending_day, self._pending, sid)
        self._pending = 0.0
        self._pending_day = None
        self._flushed = self.now()

    def set_session(self, session_id: int | None, day: str | None = None) -> None:
        with self._lock:
            self._flush()
            self.session_id = session_id
            self.session_day = day if session_id is not None else None
            self._boundary = self.now()


# ---------------------------------------------------------------------- streak and calendar


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def practice_days(days: dict[str, dict]) -> set[str]:
    return {d for d, v in days.items() if v["seconds"] >= config.PRACTICE_DAY_SECONDS - EPS or v["sessions"] > 0}


def streak(days: dict[str, dict], today_s: str) -> dict:
    """Days in a row with practice, up to today (today counts when it has practice; if not yet,
    the streak runs to yesterday). One missed day in each week (Monday-Sunday) is covered by the
    streak freeze; 2 missed days in a row break the streak. A frozen day does not add to the count.
    """
    done = practice_days(days)
    day = _date(today_s)
    if today_s not in done:
        day -= dt.timedelta(days=1)  # today is not over yet
    first = day
    count = 0
    frozen: list[str] = []
    weeks_used: set[tuple[int, int]] = set()
    for _ in range(5000):
        key = day.isoformat()
        if key in done:
            count += 1
        else:
            week = day.isocalendar()[:2]
            prev = (day - dt.timedelta(days=1)).isoformat()
            # A freeze covers one missed day between 2 practice days (or yesterday, when the
            # user can still practice today). One freeze in each week.
            if (count > 0 or day == first) and prev in done and week not in weeks_used \
                    and config.STREAK_FREEZES_PER_WEEK > 0:
                weeks_used.add(week)
                frozen.append(key)
            else:
                break
        day -= dt.timedelta(days=1)
    this_week = _date(today_s).isocalendar()[:2]
    return {"days": count, "frozen": sorted(frozen), "freeze_left": this_week not in weeks_used,
            "today_done": today_s in done}


def calendar(days: dict[str, dict], today_s: str, goal_minutes: int, weeks: int = 18) -> dict:
    """Heat map: whole weeks (Monday first), the last `weeks` weeks up to this week."""
    end = _date(today_s)
    start = end - dt.timedelta(days=end.weekday() + 7 * (weeks - 1))
    st = streak(days, today_s)
    frozen = set(st["frozen"])
    cells = []
    d = start
    while d <= end + dt.timedelta(days=6 - end.weekday()):
        key = d.isoformat()
        v = days.get(key, {"seconds": 0, "sessions": 0})
        minutes = v["seconds"] / 60.0
        ratio = minutes / goal_minutes if goal_minutes else 0
        level = 0 if minutes < 0.5 and not v["sessions"] else 1 if ratio < 0.5 else 2 if ratio < 1 else 3
        cells.append({"day": key, "minutes": round(minutes, 1), "sessions": v["sessions"], "level": level,
                      "frozen": key in frozen, "future": d > end})
        d += dt.timedelta(days=1)
    return {"start": start.isoformat(), "weeks": weeks, "cells": cells}


# ---------------------------------------------------------------------- the daily plan


def block_minutes(total: float) -> dict[str, float]:
    """Share of each block, rounded to half minutes; the song block gets the rest."""
    out = {k: max(0.5, round(total * share * 2) / 2) for k, share in config.SESSION_SHARES if k != "song"}
    out["song"] = total - sum(out.values())
    return out


def hardest_part(progress: dict | None) -> int | None:
    """The part with the most errors in its last runs (None without errors)."""
    if not progress:
        return None
    best, worst = None, 0
    for part, hist in (progress.get("part_errors") or {}).items():
        n = sum(hist)
        if n > worst:
            best, worst = int(part), n
    return best


def _hands_for(song: dict, entry: dict | None, level: int) -> list[str]:
    if entry:
        return list(entry["hands"])
    present = songs.hands_of(song)
    if level >= 3:
        return present
    return ["R"] if "R" in present else present[:1]


def warmup_pattern(song: dict, hands: list[str], part: int | None, n: int = config.WARMUP_NOTES) -> dict:
    """A short pattern (n stops) from the song: the hardest part, else the first hand move, else the start."""
    notes = sorted((x for x in song["notes"] if x["hand"] in hands), key=lambda x: (x["start"], x["pitch"]))
    starts = sorted({x["start"] for x in notes})
    begin = starts[0] if starts else 0.0
    why = "start"
    if part is not None and song.get("sections") and part < len(song["sections"]):
        begin = song["sections"][part]["start"]
        why = "hard_part"
    else:
        moves = sorted(p["start"] for p in song.get("hand_positions", []) if p["hand"] in hands and p["start"] > 0)
        if moves:
            i = max(0, next((k for k, s in enumerate(starts) if s >= moves[0] - EPS), 0) - 2)
            begin = starts[i] if starts else 0.0
            why = "hand_move"
    chosen = [s for s in starts if s >= begin - EPS][:n]
    steps = []
    for s in chosen:
        group = [x for x in notes if abs(x["start"] - s) < EPS]
        if len(group) == 1:
            steps.append({"any": [group[0]["pitch"]], "finger": group[0]["finger"], "hand": group[0]["hand"]})
        else:
            steps.append({"all": sorted(x["pitch"] for x in group),
                          "fingers": {str(x["pitch"]): x["finger"] for x in group},
                          "hand": "".join(sorted({x["hand"] for x in group}, key="RL".index))})
    positions = [p for p in song.get("hand_positions", []) if p["hand"] in hands]
    return {"steps": steps, "from_beat": begin, "why": why, "part": part,
            "hand_positions": positions, "song_id": song["id"]}


def plan(store: Store, course: Course, minutes: int | None = None, song_id: str | None = None,
         day: str | None = None) -> dict:
    """The plan for today's session (it does not start the session)."""
    settings = habit_settings(store)
    minutes = minutes if minutes in config.SESSION_MINUTES else settings["session_minutes"]
    level = course.level()
    sid = song_id or settings["song_id"]
    song = get_song(sid) if sid else None
    entry = None
    if song is None or song.get("source") == "course":
        cur = course.current_song()
        if cur is None:  # all levels done: the ladder song with the lowest best result
            progress = store.song_progress()
            ladder = [e for e in _ladder()]
            cur = min(ladder, key=lambda e: (progress.get(e["song_id"], {}).get("best_full") or 0))
        entry = cur
        song = get_song(cur["song_id"])
    else:
        entry = ladder_entry(song["id"])
    hands = _hands_for(song, entry, level)
    progress = store.song_progress()
    hard = hardest_part(progress.get(song["id"]))
    mins = block_minutes(minutes)

    # The weakest skill picks the warm-up hands (PLAN 9.4).
    choices = ["keys", "rhythm"] + [k for h, k in (("R", "right"), ("L", "left")) if h in hands]
    if set(hands) >= {"R", "L"}:
        choices.append("coordination")
    focus = skills.weakest(store, choices)
    warm_hands = {"right": ["R"], "left": ["L"]}.get(focus, hands)
    warm = warmup_pattern(song, warm_hands, hard)
    # Wait mode first; when the keys are learned (step 1), the whole song is played along.
    keys_ok = bool((progress.get(song["id"]) or {}).get("keys_ok"))
    song_steps = []
    if hard is not None:
        song_steps.append({"section": hard, "speed": 0.6, "label": "hard_part", "mode": "wait"})
    song_steps.append({"section": None, "speed": None, "label": "whole", "mode": "play" if keys_ok else "wait"})

    # Review: a done song (not today's song), the one played least recently; its hardest part.
    done = [(r.get("last_played") or 0, sid2) for sid2, r in progress.items() if r["done"] and sid2 != song["id"]
            and get_song(sid2) is not None]
    due = [r for r in review.due(store, day or today(), "section")
           if get_song(r["song_id"]) is not None and r["song_id"] != song["id"]]
    review_mode = "wait"
    review_due = None
    if due:
        r = due[0]
        review_song = get_song(r["song_id"])
        review_part = r["section"] if review_song.get("sections") and r["section"] < len(review_song["sections"]) else None
        review_hands = _hands_for(review_song, ladder_entry(review_song["id"]), level)
        review_why = "due"
        review_mode = "play"
        review_due = r["due"]
    elif done:
        review_id = min(done)[1]
        review_song = get_song(review_id)
        review_part = hardest_part(progress.get(review_id))
        if review_part is None:
            runs = progress[review_id]["runs"]
            review_part = runs % max(1, len(review_song.get("sections") or [1]))
        review_hands = _hands_for(review_song, ladder_entry(review_id), level)
        review_why = "done_song"
    else:
        review_song, review_hands = song, hands
        review_part = hard if hard is not None else 0
        review_why = "current_song"
    if not review_song.get("sections"):
        review_part = None
    ifocus = skills.weakest(store, ["keys", "ear"]) or "keys"

    blocks = [
        {"kind": "warmup", "minutes": mins["warmup"], "song_id": song["id"], "title": song["title"],
         "drill": {"kind": "steps", "id": f"warmup:{song['id']}", "steps": warm["steps"], "tries": 3,
                   "source": "warmup", "ref": song["id"]},
         "pattern": warm, "focus": focus, "hands": warm_hands},
        {"kind": "song", "minutes": mins["song"], "song_id": song["id"], "title": song["title"], "hands": hands,
         "steps": song_steps, "hard_part": hard, "level": entry["level"] if entry else song.get("level"),
         "ladder": entry is not None},
        {"kind": "review", "minutes": mins["review"], "song_id": review_song["id"], "title": review_song["title"],
         "hands": review_hands, "section": review_part, "why": review_why, "mode": review_mode,
         "due": review_due},
        {"kind": "intuition", "minutes": mins["intuition"], "exercise": "find_key", "focus": ifocus,
         "drill": {"kind": "find_key", "id": "find_key", "rounds": config.FIND_KEY_ROUNDS, "source": "find_key"}},
    ]
    return {"minutes": minutes, "level": level, "blocks": blocks, "song_id": song["id"]}


def _ladder():
    from .course import ladder_entries

    return ladder_entries()


# ---------------------------------------------------------------------- sessions


class Sessions:
    def __init__(self, store: Store, course: Course, activity: Activity, now: Callable[[], float] = time.time,
                 day: Callable[[], str] = today):
        self.store = store
        self.course = course
        self.activity = activity
        self.now = now
        self.day = day
        self._lock = threading.Lock()
        self.active_id: int | None = None

    def _close_old(self, d: str) -> None:
        """Close the open sessions of earlier days (the app stayed open past midnight, or it was
        closed during a session). Call with self._lock held."""
        for s in self.store.open_sessions_before(d):
            ends = [s["started"] + s["seconds"]]
            for b in s["blocks"]:
                if isinstance(b.get("started"), (int, float)):
                    ends.append(b["started"] + float(b.get("seconds") or 0))
            if self.active_id == s["id"]:
                self.active_id = None
                self.activity.set_session(None)
            self._close(s, max(ends))

    def _close(self, s: dict, ended: float) -> None:
        if any(b.get("status") == "done" for b in s["blocks"]):
            self.store.count_session(s["day"])
        self.store.update_session(s["id"], ended=ended, summary=self._summary(s, ended))

    def today(self) -> dict:
        """Today's plan, the open or finished sessions of today, and the habit data."""
        with self._lock:
            d = self.day()
            self._close_old(d)
            if self.active_id is not None:
                cur = self.store.session(self.active_id)
                if cur is None or cur["ended"] is not None or cur["day"] != d:
                    self.active_id = None
                    self.activity.set_session(None)
            list_ = self.store.sessions_on(d)
            open_ = next((s for s in reversed(list_) if s["ended"] is None), None)
            if open_ is not None and self.active_id is None:
                self.active_id = open_["id"]
                self.activity.set_session(open_["id"], d)
        return {"day": d, "plan": open_["plan"] if open_ else plan(self.store, self.course, day=d),
                "session": _public(open_) if open_ else None,
                "finished": [_public(s) for s in list_ if s["ended"] is not None],
                "habit": self.habit()}

    def start(self, minutes: int | None = None) -> dict:
        with self._lock:
            d = self.day()
            self._close_old(d)
            for s in self.store.sessions_on(d):
                if s["ended"] is None:  # one open session at a time: close the old one
                    self.store.update_session(s["id"], ended=self.now())
            p = plan(self.store, self.course, minutes, day=d)
            sid = self.store.add_session(d, p["minutes"], p, self.now())
            self.store.update_session(sid, blocks=[{"status": "todo"} for _ in p["blocks"]])
            self.active_id = sid
            self.activity.set_session(sid, d)
            return _public(self.store.session(sid))

    def block(self, session_id: int, index: int, status: str, seconds: float | None = None,
              result: dict | None = None, paused: float | None = None) -> dict:
        """Set the status of a block. "active" keeps the first start time ("started", server time)
        and "paused" (seconds the window was hidden), so the timer goes on after a reload."""
        with self._lock:
            s = self._open(session_id)
            if not isinstance(index, int) or not 0 <= index < len(s["plan"]["blocks"]):
                raise SessionError("The app cannot find this step of the practice.")
            if status not in ("done", "skipped", "active"):
                raise SessionError("The app does not know this choice.")
            blocks = s["blocks"] or [{"status": "todo"} for _ in s["plan"]["blocks"]]
            b = dict(blocks[index])
            b["status"] = status
            if isinstance(seconds, (int, float)) and not isinstance(seconds, bool) and seconds >= 0:
                b["seconds"] = round(float(min(seconds, 4 * 3600)), 1)
            if isinstance(result, dict):
                b["result"] = {k: v for k, v in result.items() if isinstance(v, (int, float, str, bool, type(None)))}
            if status == "active":
                b.setdefault("started", self.now())
                if isinstance(paused, (int, float)) and not isinstance(paused, bool) and paused >= 0:
                    b["paused"] = round(float(min(paused, 24 * 3600)), 1)
            blocks[index] = b
            self.store.update_session(session_id, blocks=blocks)
            return _public(self.store.session(session_id))

    def end(self, session_id: int) -> dict:
        with self._lock:
            s = self._open(session_id, allow_ended=True)
            if s["ended"] is not None and s["summary"]:
                return _public(s)
            self.activity.flush()
            s = self.store.session(session_id)
            self._close(s, self.now())
            if self.active_id == session_id:
                self.active_id = None
                self.activity.set_session(None)
            return _public(self.store.session(session_id))

    def _summary(self, s: dict, ended: float) -> dict:
        skills = [r for r in self.store.query(
            "SELECT skill_id FROM skills_done WHERE session_id = ? OR (t >= ? AND t <= ?)",
            (s["id"], s["started"], ended + 1))]
        names = []
        for r in skills:
            sk = self.course.skill(r["skill_id"])
            if sk and sk["name"] not in names:
                names.append(sk["name"])
        best = None
        for a in self.store.attempts(kind="song", session_id=s["id"], limit=500):
            if a["accuracy"] is None or not a["completed"]:
                continue
            if best is None or (a["accuracy"], a["section"] is None) > (best["accuracy"], best["whole"]):
                song = get_song(a["item"])
                best = {"accuracy": a["accuracy"], "song_id": a["item"], "title": song["title"] if song else a["item"],
                        "speed": a["speed"], "whole": a["section"] is None}
        fk = [a for a in self.store.attempts(kind="drill", session_id=s["id"], limit=50) if a["item"] == "find_key"]
        find_key = None
        if fk and fk[0]["data"].get("times"):
            times = fk[0]["data"]["times"]
            find_key = round(sum(times) / len(times), 1)
        st = streak(self.store.all_days(), s["day"])
        blocks = s["blocks"]
        return {"seconds": round(self.store.session(s["id"])["seconds"], 1),
                "wall_seconds": round(ended - s["started"], 1),
                "minutes": round(self.store.session(s["id"])["seconds"] / 60.0, 1),
                "new_skills": names, "best": best, "find_key_seconds": find_key,
                "streak": st["days"], "freeze_left": st["freeze_left"],
                "blocks_done": sum(1 for b in blocks if b.get("status") == "done"),
                "blocks_skipped": sum(1 for b in blocks if b.get("status") == "skipped"),
                "day_minutes": round(self.store.day_seconds(s["day"]) / 60.0, 1)}

    def _open(self, session_id: int, allow_ended: bool = False) -> dict:
        s = self.store.session(session_id) if isinstance(session_id, int) else None
        if s is None:
            raise SessionError("The app cannot find this practice. Start today's practice again.")
        if s["ended"] is not None and not allow_ended:
            raise SessionError("This practice is finished. Start a new practice.")
        return s

    def habit(self) -> dict:
        self.activity.flush()
        d = self.day()
        days = self.store.all_days()
        settings = habit_settings(self.store)
        st = streak(days, d)
        return {"today_minutes": round(days.get(d, {"seconds": 0})["seconds"] / 60.0, 1),
                "goal_minutes": settings["goal_minutes"], "session_minutes": settings["session_minutes"],
                "streak": st, "calendar": calendar(days, d, settings["goal_minutes"]),
                "settings": settings}


def _public(s: dict | None) -> dict | None:
    if s is None:
        return None
    return {"id": s["id"], "day": s["day"], "started": s["started"], "ended": s["ended"],
            "planned_min": s["planned_min"], "plan": s["plan"], "blocks": s["blocks"],
            "seconds": round(s["seconds"], 1), "summary": s["summary"]}


# ---------------------------------------------------------------------- reminder (macOS)


def osascript_notify(text: str = config.NOTIFY_TEXT) -> bool:
    """Show a macOS notification with osascript (no new packages). False if it did not work."""
    safe = text.replace("\\", "").replace('"', "")
    try:
        r = subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "Riyaz"'],
                           capture_output=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        log.warning("osascript notification failed")
        return False


class Reminder:
    """Optional daily reminder at a set time (off by default, PLAN 9.2). Sends one notification
    a day, after the set time, only if today's practice time is below the goal."""

    def __init__(self, store: Store, activity: Activity, notify: Callable[[str], bool] = osascript_notify,
                 now: Callable[[], dt.datetime] = dt.datetime.now):
        self.store = store
        self.activity = activity
        self.notify = notify
        self.now = now
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check(self) -> bool:
        """True if it sent the notification now."""
        s = habit_settings(self.store)
        if not s["notify"]:
            return False
        now = self.now()
        day = now.date().isoformat()
        hh, mm = (int(x) for x in s["notify_time"].split(":"))
        if (now.hour, now.minute) < (hh, mm) or self.store.get("habit.notified_day") == day:
            return False
        self.activity.flush()
        if self.store.day_seconds(day) >= s["goal_minutes"] * 60:
            return False
        self.store.set("habit.notified_day", day)
        return bool(self.notify(config.NOTIFY_TEXT))

    def start(self) -> None:
        if self._thread is not None:
            return

        def loop():
            while not self._stop.wait(config.NOTIFY_CHECK_S):
                try:
                    self.check()
                except Exception:
                    log.exception("Reminder check failed")

        self._thread = threading.Thread(target=loop, name="riyaz-reminder", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
