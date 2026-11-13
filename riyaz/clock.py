"""One clock for all MIDI events and the UI clock sync.

time.perf_counter() on macOS uses mach_absolute_time, so values from 2 processes on the
same Mac can be compared. The UI keeps an offset to this clock (ping/pong, median of 5).
"""

from __future__ import annotations

import time


def now() -> float:
    """Seconds on the shared monotonic clock."""
    return time.perf_counter()


def pong(ping: dict) -> dict:
    """Answer a UI ping. The UI computes offset = t_server - (t0 + t1) / 2."""
    return {"type": "pong", "id": ping.get("id"), "t_client": ping.get("t_client"), "t_server": now()}
