"""Settings, paths and limits for Riyaz.

All numbers that other modules use live here, so that they are easy to find and change.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Riyaz"

# --- Server ---------------------------------------------------------------

DEFAULT_PORT = 8020  # DocKit uses 8010, passport-photo-tool uses 8000.
HOST = "127.0.0.1"


ALLOWED_HOSTS = ("127.0.0.1", "localhost")  # Host header check (DNS rebinding)


def requested_port() -> int:
    return int(os.environ.get("PORT", str(DEFAULT_PORT)))


# --- Paths ----------------------------------------------------------------


def base_path() -> Path:
    """Folder that holds static/ (inside the .app when frozen)."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def static_path() -> Path:
    return base_path() / "static"


def data_dir() -> Path:
    """User data folder. Tests set RIYAZ_DATA_DIR to a temp folder."""
    override = os.environ.get("RIYAZ_DATA_DIR")
    if override:
        path = Path(override)
    else:
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "riyaz.sqlite3"


# --- Keyboard (Yamaha YPT-320) ---------------------------------------------

KEY_LOW = 36  # C1 in Yamaha naming, C2 in scientific naming
KEY_HIGH = 96  # C6 in Yamaha naming, C7 in scientific naming
MIDDLE_C = 60

# --- MIDI service ----------------------------------------------------------

HOTPLUG_INTERVAL_S = 2.0
SUSTAIN_CC = 64
LOCAL_CONTROL_CC = 122
# Port names that are never a real keyboard. They do not count for the automatic choice.
IGNORED_PORT_PREFIXES = ("IAC Driver", "Riyaz Out")


def port_filter() -> str | None:
    """RIYAZ_PORT_FILTER=prefix: the app sees only MIDI ports whose name starts with prefix.

    Tests and tools use it, so that a real keyboard that is plugged in does not change the result.
    """
    return os.environ.get("RIYAZ_PORT_FILTER") or None

# --- Setup and calibration -------------------------------------------------

SETUP_TEST_TIMEOUT_S = 10.0  # "Press any key." If nothing comes in this time, show the help text.
TOUCH_SAMPLE_COUNT = 8  # "Play 4 notes soft, then 4 notes loud."
TOUCH_MIN_SPREAD = 8  # Smaller velocity spread = touch response is probably off.

# --- Songs (PLAN 5.1) -------------------------------------------------------


def songs_path() -> Path:
    """Built-in songs (data/songs/*.json). Inside the .app when frozen."""
    return base_path() / "data" / "songs"


def extra_song_dir() -> Path | None:
    """RIYAZ_EXTRA_SONG_DIR=folder: also load songs from this folder (test songs, checks)."""
    value = os.environ.get("RIYAZ_EXTRA_SONG_DIR")
    return Path(value) if value else None


# --- Practice: song clock and wait mode (PLAN 4 Timing, 6.3, 6.4) ----------------

SPEED_MIN = 0.25  # speed slider 25 %-150 %
SPEED_MAX = 1.5
WAIT_CHORD_WINDOW_S = 0.3  # keys of one stop: down together, or pressed in order within this time
WAIT_EARLY_BEATS = 0.5  # a correct key this much before its note reaches the line counts
PRACTICE_TICK_S = 0.005  # song clock check while the song runs (wait stop, end, keyboard output)
# A note_on with the same raw pitch as a note that the app sent to the keyboard, less than this
# time after the send, is the keyboard's echo (MIDI thru), not a key press. It is dropped.
ECHO_WINDOW_S = 0.05
SKILL_BREAK_LEAD_BEATS = 0.5  # a skill moment stops the song this much before the new skill
SEEK_LEAD_BEATS = 1.0  # after a skill moment the song starts this much before the place

# --- MIDI import (PLAN 11.1, Phase 3a) ---------------------------------------------


def user_songs_path() -> Path:
    """Imported songs: <data dir>/songs/<id>.json, with the original file <id>.mid next to it."""
    return data_dir() / "songs"


IMPORT_MAX_BYTES = 2 * 1024 * 1024  # a larger file is not a song to practice (and can be an attack)
IMPORT_MAX_NOTES = 20000  # notes in the selected tracks (drums and other tracks do not count)
IMPORT_MAX_RAW_NOTES = 200000  # every note_on in the file (memory limit; a 2 MB file can hold about 700000)
IMPORT_MAX_TRACKS = 128
IMPORT_MAX_MINUTES = 30  # a longer song is not a song to practice (or a damaged file)
IMPORT_PENDING_MAX = 8  # uploaded files that wait for the track choice (oldest is removed)
IMPORT_QUANTIZE = (8, 16)  # grid choices: 1/8 and 1/16 notes
SECTION_BARS = 4  # imported songs: a new part every 4 bars (or at a long pause)
USER_LEVEL_DEFAULT = 1  # a new user (the course state, riyaz/course.py, gives the real level)

# --- Course, daily session and habit (PLAN 8, 9.1, 9.2, Phase 3b) ----------------------------


def course_path() -> Path:
    """Course content (data/course/*.json): terms, keyboard basics, skill moments, song ladder."""
    return base_path() / "data" / "course"


# "Song done" (PLAN 8.3: 100% speed and a score of 80 or more). Phase 3 has no play-along score
# (Phase 4), so the score is the wait-mode accuracy: the % of stops where the first key was right.
# riyaz/course.py song_done() is the one place to change when the Phase 4 score comes.
SONG_DONE_SPEED = 1.0
SONG_DONE_SCORE = 80
SKILL_TRIES = 3  # a skill moment passes after 3 correct tries (PLAN 8.2)
MAX_COURSE_LEVEL = 3  # levels with content in this version

SESSION_MINUTES = (10, 15, 20, 30)  # PLAN 9.1
SESSION_MINUTES_DEFAULT = 20
SESSION_SHARES = (("warmup", 0.10), ("song", 0.60), ("review", 0.15), ("intuition", 0.15))
GOAL_MINUTES = (5, 10, 15, 20, 30, 45, 60)
GOAL_MINUTES_DEFAULT = 20
FIND_KEY_ROUNDS = 10
WARMUP_NOTES = 6  # the short pattern of the warm-up

# Practice time = time with the hands on the keys: the time between 2 key presses counts when it
# is shorter than this (reading a short text counts; a break does not).
ACTIVITY_GAP_S = 60.0
ACTIVITY_FLUSH_S = 10.0  # write the practice time to the database at least this often
PRACTICE_DAY_SECONDS = 60.0  # a day counts for the streak with 1 minute of practice (or a finished session)
STREAK_FREEZES_PER_WEEK = 1  # PLAN 9.2: one missed day each week does not break the streak

NOTIFY_TEXT = "Time for your Riyaz."
NOTIFY_TIME_DEFAULT = "19:00"
NOTIFY_CHECK_S = 30.0
