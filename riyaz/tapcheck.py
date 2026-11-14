"""Latency calibration: "tap with the click" (PLAN 4 Timing, 15 Risks "Web Audio delay").

The app plays TAP_CLICKS clicks on the Mac (times on the server clock; the page converts them to
audio time with its clock offset and plays each click Tone.context.outputLatency early when the
browser gives it). The user presses any key with each click. Each key press goes to the nearest
click (inside half the time between clicks). offset = median(press time - click time).

The offset is the delay from the click that the user hears to the press that the app gets: sound
output, the user's ear, the MIDI cable. Play-along takes it away from each key time
(Practice.input_offset_s). Limits: at least TAP_MIN_TAPS taps; the taps must be even (median
distance from the median <= TAP_MAX_SPREAD_S); a median below 0 is stored as 0; above TAP_MAX_S
the check fails (most likely the user did not tap with the click). Re-run any time (Settings).
"""

from __future__ import annotations

import statistics
import threading
from collections.abc import Callable

from . import clock, config

KEY = "latency.offset_ms"


def offset_ms(store) -> float:
    v = store.get(KEY, 0.0)
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return min(config.TAP_MAX_S * 1000.0, max(0.0, v)) if v == v else 0.0


def compute(clicks: list[float], taps: list[float]) -> dict:
    """The result of a check: {ok, offset_ms, taps, spread_ms, reason}. Times in seconds."""
    if len(clicks) < 2:
        return {"ok": False, "offset_ms": None, "taps": 0, "spread_ms": None, "reason": "no_clicks"}
    half = (clicks[1] - clicks[0]) / 2.0
    best: dict[int, float] = {}
    for t in taps:
        i = min(range(len(clicks)), key=lambda k: abs(t - clicks[k]))
        d = t - clicks[i]
        if abs(d) < half and i not in best:  # the first press for each click
            best[i] = d
    ds = sorted(best.values())
    n = len(ds)
    if n < config.TAP_MIN_TAPS:
        return {"ok": False, "offset_ms": None, "taps": n, "spread_ms": None, "reason": "few_taps"}
    med = statistics.median(ds)
    spread = statistics.median(abs(d - med) for d in ds)
    out = {"taps": n, "spread_ms": round(spread * 1000.0, 1), "raw_ms": round(med * 1000.0, 1)}
    if spread > config.TAP_MAX_SPREAD_S:
        return {**out, "ok": False, "offset_ms": None, "reason": "uneven"}
    if med > config.TAP_MAX_S:
        return {**out, "ok": False, "offset_ms": None, "reason": "too_late"}
    return {**out, "ok": True, "offset_ms": round(max(0.0, med) * 1000.0, 1), "reason": None}


TEXTS = {
    "few_taps": "The app got less than {min} key presses with the clicks. Do the check again. "
                "Press any key on the keyboard each time that you hear the click.",
    "uneven": "Your key presses were not even. Do the check again. Press each key with the click.",
    "too_late": "Your key presses came too late after the clicks. Do the check again. "
                "Press each key with the click, not after it.",
    "no_clicks": "The app cannot start the check. Try again.",
    "not_started": "Click \"Start the check\" first.",
}


def text_of(res: dict) -> str:
    if res.get("ok"):
        ms = res["offset_ms"]
        if ms < 1:
            return "Your key presses come with the click. The app does not change the key times."
        return (f"Your key presses come {ms:.0f} ms ({ms / 1000:.2f} seconds) after the click. "
                "In Play along, the app now counts each key press this much earlier.")
    return TEXTS.get(res.get("reason") or "", TEXTS["no_clicks"]).format(min=config.TAP_MIN_TAPS)


class TapCheck:
    """One check at a time. Thread-safe: the MIDI thread calls on_midi."""

    def __init__(self, sink: Callable[[dict], None] = lambda e: None, now: Callable[[], float] = clock.now):
        self.sink = sink
        self.now = now
        self._lock = threading.Lock()
        self.clicks: list[float] = []
        self.taps: list[float] = []
        self.active = False

    def start(self) -> dict:
        with self._lock:
            t0 = self.now() + config.TAP_LEAD_S
            self.clicks = [t0 + i * config.TAP_INTERVAL_S for i in range(config.TAP_CLICKS)]
            self.taps = []
            self.active = True
            return {"clicks": list(self.clicks), "interval": config.TAP_INTERVAL_S, "now": self.now(),
                    "end": self.clicks[-1] + config.TAP_INTERVAL_S / 2.0, "min_taps": config.TAP_MIN_TAPS}

    def on_midi(self, evt: dict) -> None:
        if evt.get("type") != "note_on" or evt.get("reason") is not None or not self.active:
            return
        t = evt.get("t")
        with self._lock:
            if not self.active or t is None:
                return
            if self.clicks[0] - config.TAP_INTERVAL_S <= t <= self.clicks[-1] + config.TAP_INTERVAL_S:
                self.taps.append(float(t))
                n = len(self.taps)
            else:
                return
        self.sink({"type": "tapcheck_tap", "n": n, "t": t})

    def finish(self) -> dict:
        with self._lock:
            if not self.clicks:
                return {"ok": False, "offset_ms": None, "taps": 0, "reason": "not_started"}
            self.active = False
            res = compute(self.clicks, self.taps)
            self.clicks, self.taps = [], []
        return res

    def cancel(self) -> None:
        with self._lock:
            self.active = False
            self.clicks, self.taps = [], []
