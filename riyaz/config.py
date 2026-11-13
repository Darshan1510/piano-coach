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
