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

# --- Audio import (PLAN 11.3, Phase 5a) -------------------------------------------------------

AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a")
AUDIO_MAX_BYTES = 40 * 1024 * 1024  # about 10 minutes of MP3 or 4 minutes of CD-quality WAV
AUDIO_MAX_SECONDS = 6 * 60  # a longer recording is not one song to practice (and takes long)
AUDIO_MIN_SECONDS = 2.0
AUDIO_JOBS_MAX = 4  # finished jobs that the app keeps (oldest removed)
AUDIO_WORKER_TIMEOUT_S = 15 * 60  # the worker stops after this time
AFCONVERT = "/usr/bin/afconvert"  # macOS: M4A (AAC) -> WAV, no ffmpeg needed


def audio_tmp_path() -> Path:
    """Temporary audio files (inside the data folder, removed after each import)."""
    return data_dir() / "tmp-audio"

# --- Song editor (PLAN 11.4, Phase 5a) ----------------------------------------------------------

EDITOR_MAX_NOTES = 20000  # same limit as an import

# --- Course, daily session and habit (PLAN 8, 9.1, 9.2, Phase 3b) ----------------------------


def course_path() -> Path:
    """Course content (data/course/*.json): terms, keyboard basics, skill moments, song ladder."""
    return base_path() / "data" / "course"


# "Song done" (PLAN 8.3: 100% speed and a score of 80 or more). Phase 4: the score is the
# play-along score (0-100). Level 1 songs (wait mode first, the user is a beginner) are also done
# with a wait-mode run (% of stops where the first key was right). riyaz/course.py song_done().
SONG_DONE_SPEED = 1.0
SONG_DONE_SCORE = 80
WAIT_DONE_MAX_LEVEL = 1  # a wait-mode run can finish a ladder song of this level or lower
SKILL_TRIES = 3  # a skill moment passes after 3 correct tries (PLAN 8.2)
MAX_COURSE_LEVEL = 10  # levels with content in this version (Phase 6: Levels 9-10)

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

# --- Play-along matcher and scores (PLAN 6.4, Phase 4) ------------------------------------
# Windows are real time (seconds) at the current speed: the expected time of a note is its beat
# on the song clock (which runs at the set speed). A press inside PLAY_WINDOW_S of a note with the
# same key matches the earliest unmatched note (the nearest one when the earliest is more than
# PLAY_GOOD_S away and a later same-key note is within PLAY_GOOD_S; matcher.PlayMatcher._candidate).
PLAY_PERFECT_S = 0.05
PLAY_GOOD_S = 0.12
PLAY_WINDOW_S = 0.25  # late / early; outside = missed (and the press is an extra note)
PLAY_NEIGHBOR = 2  # an extra note 1 or 2 keys from an expected note = a wrong note (likely slip)
PLAY_SHORT_RATIO = 0.6  # "short": held less than 60% of the length ...
PLAY_SHORT_MIN_BEATS = 1.0  # ... for notes of 1 beat or longer
PLAY_STOP_GAP_S = 2.0  # no key for this long while notes were missed = the user stopped
PLAY_LOG_MAX = 4000  # notes in the run log of practice_end (feedback, preview)
# Total score = accuracy x (0.6 + 0.25 x timing + 0.15 x length), timing and length as 0-1.
SCORE_WEIGHTS = (0.6, 0.25, 0.15)
STARS = (90, 70)  # 3 stars from 90, 2 from 70, else 1

# --- Feedback: live tips and after-run findings (PLAN 7.1, 7.2) ---------------------------
TIP_INTERVAL_S = 4.0  # at most one tip each 4 seconds
TIP_EARLY_RUN = 3  # "Wait for the click." after 3 early notes in a row
TIP_SHORT_RUN = 2  # "Keep the key down longer." after 2 short notes in a row
FINDINGS_MAX = 3
HARD_SPOT_ERRORS = 2  # >= 2 errors in the same group of clicks ...
HARD_SPOT_RUNS = (2, 3)  # ... in 2 of the last 3 runs
RUSH_MS = -40.0  # mean timing error below this (over >= RUSH_MIN_NOTES notes) = rushing
DRAG_MS = 60.0  # mean timing error above this = dragging
RUSH_MIN_NOTES = 8
HAND_GAP = 20.0  # one hand's accuracy 20 points lower = hand problem
COORD_ALONE = 85.0  # each hand alone >= 85 ...
COORD_BOTH = 70.0  # ... and both hands < 70 = coordination
MOVE_NOTES = 2  # the notes right after a hand position change
MOVE_MIN_ERRORS = 2
CHORD_MIN_TIMES = 2  # keys together with a missing key >= 2 times
UNEVEN_MIN_NOTES = 8
UNEVEN_SD = 15.0  # velocity SD (0-127) without a touch range from the setup
UNEVEN_SD_SHARE = 0.25  # with the setup touch range: SD > 25% of the range
SHORT_LENGTH_SCORE = 60.0  # length score below this = "short notes"
SLIP_MIN = 3  # wrong neighbor keys: at least 3 and ...
SLIP_SHARE = 0.05  # ... at least 5% of the notes
LOOP_SLOW_SPEED = 0.6  # "Practice this part slowly" (loop at 60% speed)

# --- Automatic adapt (PLAN 7.3) -----------------------------------------------------------
ADAPT_RUNS = 3
ADAPT_FAIL = 60  # 3 runs below 60 in a row: speed - 15 points (not below 40%)
ADAPT_CLEAN = 90  # 3 runs of 90 or more: speed + 5 (or + 10 when all 3 are >= 95), up to 100%
ADAPT_DOWN = 0.15
ADAPT_UP = 0.05
ADAPT_UP_BIG = 0.10
ADAPT_UP_BIG_SCORE = 95
ADAPT_MIN_SPEED = 0.40
LEARNED_SCORE = 85  # whole song at 100% with >= 85 = "learned": spaced repetition starts
LOOP_STEP = 0.05  # PLAN 6.3 Loop: +5% after 3 clean runs

# --- Spaced repetition and skill model (PLAN 9.3, 9.4) ------------------------------------
REVIEW_GOOD = 85  # score >= 85: interval x 2
REVIEW_OK = 60  # 60-84: same interval; < 60: 1 day
REVIEW_FIRST_DAYS = 1
SKILL_HISTORY = 20  # the last 20 related results of each skill
SKILL_ALPHA = 0.3  # newer results count more (moving average)

# --- Latency calibration: "tap with the click" (PLAN 4 Timing, review fix 4) ---------------
TAP_CLICKS = 8
TAP_INTERVAL_S = 0.75  # 80 clicks a minute
TAP_LEAD_S = 1.0  # time before the first click
TAP_MIN_TAPS = 5  # at least 5 of the 8 clicks need a key press
TAP_MAX_SPREAD_S = 0.08  # median distance from the median: more = the taps were not even
TAP_MAX_S = 0.30  # the stored offset is 0-300 ms
