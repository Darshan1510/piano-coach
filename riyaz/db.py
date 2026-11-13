"""SQLite storage (one user).

Phase 1: settings (port choice, calibration). Phase 3b adds the progress tables:

- ``days``          practice seconds per day (the top bar, the daily goal, the calendar, the streak)
- ``sessions``      daily sessions (plan, block results, summary)
- ``attempts``      each song run (wait mode) and each drill (skill moment, warm-up, "Find the key")
- ``song_progress`` best result for each song, and "done" (PLAN 8.3)
- ``course``        course state (key/value: level floor, basics tasks)
- ``skills_done``   skill moments that the user passed (PLAN 8.2)
- ``terms``         unlocked music terms and "card seen" (PLAN 7.4 Rules 2-4)

Days are local dates "YYYY-MM-DD". All writes go through one lock (the MIDI thread, the practice
thread and the server thread all write).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import config

log = logging.getLogger("riyaz.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS days (
    day      TEXT PRIMARY KEY,
    seconds  REAL NOT NULL DEFAULT 0,
    sessions INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    day         TEXT NOT NULL,
    started     REAL NOT NULL,
    ended       REAL,
    planned_min REAL NOT NULL,
    plan        TEXT NOT NULL,
    blocks      TEXT NOT NULL DEFAULT '[]',
    seconds     REAL NOT NULL DEFAULT 0,
    summary     TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    t          REAL NOT NULL,
    day        TEXT NOT NULL,
    kind       TEXT NOT NULL,
    item       TEXT NOT NULL,
    session_id INTEGER,
    hands      TEXT,
    section    INTEGER,
    speed      REAL,
    completed  INTEGER NOT NULL DEFAULT 0,
    stops      INTEGER,
    wrong      INTEGER,
    accuracy   REAL,
    data       TEXT
);
CREATE INDEX IF NOT EXISTS attempts_item ON attempts(kind, item);
CREATE TABLE IF NOT EXISTS song_progress (
    song_id       TEXT PRIMARY KEY,
    runs          INTEGER NOT NULL DEFAULT 0,
    best_accuracy REAL,
    best_full     REAL,
    done          INTEGER NOT NULL DEFAULT 0,
    done_at       REAL,
    last_played   REAL,
    part_errors   TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS course (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills_done (
    skill_id   TEXT PRIMARY KEY,
    t          REAL NOT NULL,
    session_id INTEGER
);
CREATE TABLE IF NOT EXISTS terms (
    term_id     TEXT PRIMARY KEY,
    unlocked_at REAL NOT NULL,
    seen        INTEGER NOT NULL DEFAULT 0
);
"""


# Schema version in "PRAGMA user_version". 0 = a database of Phase 1-2 (settings table only, no
# version). 2 = Phase 3 (the progress tables). A later version adds a step to _MIGRATIONS; each
# step runs one time, in order, and then the version number changes in the same transaction.
SCHEMA_VERSION = 2
_MIGRATIONS: dict[int, str] = {
    2: _SCHEMA,  # Phase 3: add the progress tables (CREATE IF NOT EXISTS; settings is unchanged)
}


class Store:
    """Small thread-safe store. Settings values are JSON."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else config.db_path()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        version = self.schema_version()
        if version > SCHEMA_VERSION:
            # A newer app made this database. Use it as it is (tables are only added, never changed).
            log.warning("Database version %d is newer than this app (%d)", version, SCHEMA_VERSION)
            self._conn.executescript(_SCHEMA)
            return
        for target in sorted(_MIGRATIONS):
            if target > version:
                self._conn.executescript(f"BEGIN;\n{_MIGRATIONS[target]}\nPRAGMA user_version = {int(target)};\nCOMMIT;")
                version = target
        self._conn.executescript(_SCHEMA)  # always safe (CREATE IF NOT EXISTS)
        self._conn.commit()

    def schema_version(self) -> int:
        with self._lock:
            return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    # ------------------------------------------------------------------ settings (Phase 1)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ generic

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid or 0

    # ------------------------------------------------------------------ practice time per day

    def add_seconds(self, day: str, seconds: float, session_id: int | None = None) -> None:
        if seconds <= 0:
            return
        with self._lock:
            self._conn.execute(
                "INSERT INTO days(day, seconds) VALUES(?, ?) "
                "ON CONFLICT(day) DO UPDATE SET seconds = seconds + excluded.seconds", (day, seconds))
            if session_id is not None:
                self._conn.execute("UPDATE sessions SET seconds = seconds + ? WHERE id = ?", (seconds, session_id))
            self._conn.commit()

    def day_seconds(self, day: str) -> float:
        rows = self.query("SELECT seconds FROM days WHERE day = ?", (day,))
        return float(rows[0]["seconds"]) if rows else 0.0

    def days(self, first: str, last: str) -> dict[str, dict]:
        """{day: {"seconds", "sessions"}} for first <= day <= last."""
        rows = self.query("SELECT day, seconds, sessions FROM days WHERE day BETWEEN ? AND ?", (first, last))
        return {r["day"]: {"seconds": r["seconds"], "sessions": r["sessions"]} for r in rows}

    def all_days(self) -> dict[str, dict]:
        rows = self.query("SELECT day, seconds, sessions FROM days")
        return {r["day"]: {"seconds": r["seconds"], "sessions": r["sessions"]} for r in rows}

    def count_session(self, day: str) -> None:
        self.execute("INSERT INTO days(day, sessions) VALUES(?, 1) "
                     "ON CONFLICT(day) DO UPDATE SET sessions = sessions + 1", (day,))

    # ------------------------------------------------------------------ course state

    def course_get(self, key: str, default: Any = None) -> Any:
        rows = self.query("SELECT value FROM course WHERE key = ?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def course_set(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO course(key, value) VALUES(?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))

    def skills_done(self) -> dict[str, dict]:
        return {r["skill_id"]: r for r in self.query("SELECT skill_id, t, session_id FROM skills_done")}

    def mark_skill(self, skill_id: str, session_id: int | None = None, t: float | None = None) -> bool:
        """True if the skill is new."""
        with self._lock:
            cur = self._conn.execute("INSERT OR IGNORE INTO skills_done(skill_id, t, session_id) VALUES(?, ?, ?)",
                                     (skill_id, time.time() if t is None else t, session_id))
            self._conn.commit()
            return cur.rowcount > 0

    def terms(self) -> dict[str, dict]:
        return {r["term_id"]: r for r in self.query("SELECT term_id, unlocked_at, seen FROM terms")}

    def unlock_term(self, term_id: str, t: float | None = None) -> bool:
        """True if the term is new."""
        with self._lock:
            cur = self._conn.execute("INSERT OR IGNORE INTO terms(term_id, unlocked_at) VALUES(?, ?)",
                                     (term_id, time.time() if t is None else t))
            self._conn.commit()
            return cur.rowcount > 0

    def term_seen(self, term_id: str) -> None:
        self.execute("UPDATE terms SET seen = 1 WHERE term_id = ?", (term_id,))

    def reset_course(self) -> None:
        with self._lock:
            for table in ("course", "skills_done", "terms", "song_progress"):
                self._conn.execute(f"DELETE FROM {table}")
            self._conn.commit()

    # ------------------------------------------------------------------ attempts and song progress

    def add_attempt(self, *, kind: str, item: str, day: str, t: float | None = None, session_id: int | None = None,
                    hands: list | None = None, section: int | None = None, speed: float | None = None,
                    completed: bool = False, stops: int | None = None, wrong: int | None = None,
                    accuracy: float | None = None, data: dict | None = None) -> int:
        return self.execute(
            "INSERT INTO attempts(t, day, kind, item, session_id, hands, section, speed, completed, stops, wrong, "
            "accuracy, data) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time() if t is None else t, day, kind, item, session_id, "".join(hands) if hands else None,
             section, speed, int(bool(completed)), stops, wrong, accuracy, json.dumps(data) if data else None))

    def attempts(self, kind: str | None = None, item: str | None = None, session_id: int | None = None,
                 limit: int = 200) -> list[dict]:
        where, params = [], []
        for col, val in (("kind", kind), ("item", item), ("session_id", session_id)):
            if val is not None:
                where.append(f"{col} = ?")
                params.append(val)
        sql = "SELECT * FROM attempts" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self.query(sql + " ORDER BY t DESC, id DESC LIMIT ?", (*params, limit))
        for r in rows:
            r["data"] = json.loads(r["data"]) if r["data"] else {}
        return rows

    def song_progress(self, song_id: str | None = None) -> dict[str, dict]:
        sql = "SELECT * FROM song_progress" + (" WHERE song_id = ?" if song_id else "")
        rows = self.query(sql, (song_id,) if song_id else ())
        out = {}
        for r in rows:
            r["part_errors"] = json.loads(r["part_errors"] or "{}")
            r["done"] = bool(r["done"])
            out[r["song_id"]] = r
        return out

    def update_song_progress(self, song_id: str, *, accuracy: float | None, full: bool, done: bool,
                             part_errors: dict[int, int], t: float | None = None) -> dict:
        """One wait-mode run. Returns the new row. part_errors: errors per part in this run."""
        t = time.time() if t is None else t
        with self._lock:
            row = self.song_progress(song_id).get(song_id)
            if row is None:
                row = {"song_id": song_id, "runs": 0, "best_accuracy": None, "best_full": None, "done": False,
                       "done_at": None, "last_played": None, "part_errors": {}}
            row["runs"] += 1
            row["last_played"] = t
            if accuracy is not None:
                row["best_accuracy"] = accuracy if row["best_accuracy"] is None else max(row["best_accuracy"], accuracy)
                if full:
                    row["best_full"] = accuracy if row["best_full"] is None else max(row["best_full"], accuracy)
            if done and not row["done"]:
                row["done"] = True
                row["done_at"] = t
            # Errors per part: the last 3 runs that played the part (PLAN 7.2 "2 of the last 3 runs").
            hist = row["part_errors"]
            for part, n in part_errors.items():
                hist[str(part)] = (hist.get(str(part), []) + [int(n)])[-3:]
            self._conn.execute(
                "INSERT INTO song_progress(song_id, runs, best_accuracy, best_full, done, done_at, last_played, "
                "part_errors) VALUES(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(song_id) DO UPDATE SET runs = excluded.runs, "
                "best_accuracy = excluded.best_accuracy, best_full = excluded.best_full, done = excluded.done, "
                "done_at = excluded.done_at, last_played = excluded.last_played, part_errors = excluded.part_errors",
                (song_id, row["runs"], row["best_accuracy"], row["best_full"], int(row["done"]), row["done_at"],
                 row["last_played"], json.dumps(hist)))
            self._conn.commit()
            return row

    # ------------------------------------------------------------------ sessions

    def add_session(self, day: str, planned_min: float, plan: dict, t: float | None = None) -> int:
        return self.execute("INSERT INTO sessions(day, started, planned_min, plan) VALUES(?, ?, ?, ?)",
                            (day, time.time() if t is None else t, planned_min, json.dumps(plan)))

    def session(self, session_id: int) -> dict | None:
        rows = self.query("SELECT * FROM sessions WHERE id = ?", (session_id,))
        return self._session_row(rows[0]) if rows else None

    def open_sessions_before(self, day: str) -> list[dict]:
        """Sessions of earlier days that were never closed (the app was closed, or the day changed)."""
        return [self._session_row(r) for r in self.query(
            "SELECT * FROM sessions WHERE ended IS NULL AND day < ? ORDER BY id", (day,))]

    def sessions_on(self, day: str) -> list[dict]:
        return [self._session_row(r) for r in self.query("SELECT * FROM sessions WHERE day = ? ORDER BY id", (day,))]

    def update_session(self, session_id: int, *, blocks: list | None = None, ended: float | None = None,
                       summary: dict | None = None) -> None:
        sets, params = [], []
        if blocks is not None:
            sets.append("blocks = ?")
            params.append(json.dumps(blocks))
        if ended is not None:
            sets.append("ended = ?")
            params.append(ended)
        if summary is not None:
            sets.append("summary = ?")
            params.append(json.dumps(summary))
        if sets:
            self.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", (*params, session_id))

    @staticmethod
    def _session_row(r: dict) -> dict:
        r["plan"] = json.loads(r["plan"])
        r["blocks"] = json.loads(r["blocks"] or "[]")
        r["summary"] = json.loads(r["summary"]) if r["summary"] else None
        return r
