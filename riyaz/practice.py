"""Practice session: the song clock, watch mode and wait mode (PLAN 4 Timing, 6.3, 6.4).

The backend is the source of truth for song time. The song clock is a line:

    beat(t) = anchor_beat + (t - anchor_t) * rate        rate = bpm * speed / 60 (beats per second)

``t`` is clock.now() (the same clock as the MIDI event stamps). Each change (start, pause,
speed, a wait stop that is done, loop) sets a new anchor and sends a ``practice`` event. The
UI keeps a clock offset (ping/pong, median of 5) and draws ``beat(server_now)`` at 60 fps.

Wait mode: the clock stops at the next stop point (``hold_beat``) until the user presses the
expected keys (riyaz/matcher.py). The UI clamps to ``hold_beat`` too, so it stops on time.

Events (WebSocket, all new in Phase 2; Phase 1 events do not change):
  practice        the full state (see state())
  practice_hit    {pitch, stop, song_id, run}                  a correct key
  practice_wrong  {pitch, expected, beat, stop, song_id, run}  a wrong key: no advance, logged
  practice_end    {completed, mode, wrong, stops, seconds, ...}
Phase 3b (fields added, old fields kept):
  practice_end    + accuracy (% of stops with a right first key), clean_stops, section, errors
  practice_skill  {skill, beat, song_id, run}: the song stopped before a new skill (PLAN 8.2)
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from . import clock, config
from .matcher import EPS, WaitMatcher

log = logging.getLogger("riyaz.practice")

MODES = ("watch", "wait")
OUTPUTS = ("mac", "keyboard")


class PracticeError(ValueError):
    """The text is for the user (PLAN 7.4 plain words, ASD-STE100 sentences)."""


class EchoGuard:
    """Drops the notes that the app sent to the keyboard when they come back on MIDI IN.

    Some keyboards (and MIDI thru) send the notes that they receive back out. Without this guard,
    a song note that the app plays on the keyboard speaker lights the key and counts as a press.
    A note_on with the same raw pitch less than ECHO_WINDOW_S after a send is an echo. Its
    note_off is dropped too. A real press of the same key after the window counts.
    Thread-safe: the practice thread records sends, the MIDI thread asks.
    """

    def __init__(self, window: float = config.ECHO_WINDOW_S):
        self.window = window
        self._lock = threading.Lock()
        self._sent: deque[tuple[int, float]] = deque(maxlen=64)  # (raw pitch, send time)
        self._held: set[tuple[int, int]] = set()  # (channel, raw pitch) of echoes that are down

    def sent(self, raw: int, t: float) -> None:
        with self._lock:
            self._sent.append((raw, t))

    def is_echo(self, press: bool, channel: int, raw: int, t: float) -> bool:
        with self._lock:
            if not press:
                if (channel, raw) in self._held:
                    self._held.discard((channel, raw))
                    return True
                return False
            for i, (r, ts) in enumerate(self._sent):
                if r == raw and abs(t - ts) <= self.window:
                    del self._sent[i]  # one echo for each send
                    self._held.add((channel, raw))
                    return True
            return False


class Practice:
    def __init__(self, sink: Callable[[dict], None], midi=None, now: Callable[[], float] = clock.now,
                 threaded: bool = True):
        self.sink = sink
        self.midi = midi
        self.now = now
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._closed = False
        self.seq = 0
        self.run = 0  # +1 at each start: a pause for an older run is ignored (requests can cross)
        self.song: dict | None = None
        self.echo = EchoGuard()
        self._reset_fields()
        self._thread = None
        if threaded:
            self._thread = threading.Thread(target=self._run, name="riyaz-practice", daemon=True)
            self._thread.start()

    def _reset_fields(self) -> None:
        self.mode = "wait"
        self.hands: tuple[str, ...] = ("R",)
        self.speed = 1.0
        self.rate = 1.0
        self.range_start = 0.0
        self.range_end = 0.0
        self.section: int | None = None
        self.loop = False
        self.count_in = 0.0
        self.accompany = True
        self.output = "mac"
        self.anchor_t = 0.0
        self.anchor_beat = 0.0
        self.running = False
        self.paused = False
        self.pause_reason: str | None = None
        self.done = False
        self.waiting = False
        self.passes = 0
        self.wrong = 0
        self.started_t = 0.0
        self.matcher: WaitMatcher | None = None
        self.breaks: list[tuple[float, str]] = []  # (at beat, skill id): stop before a new skill
        self._app_notes: list[dict] = []
        self._out_i = 0
        self._sounding: list[tuple[float, int]] = []  # (off time, pitch) on the keyboard output

    # ------------------------------------------------------------------ life cycle

    def close(self) -> None:
        msgs = []
        with self._lock:
            self._closed = True
            msgs = self._all_off()
        self._send(msgs)
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._closed:
            self._wake.wait(config.PRACTICE_TICK_S if self.running else 0.1)
            self._wake.clear()
            try:
                self.tick()
            except Exception:  # never let the clock thread die
                log.exception("Practice clock error")

    # ------------------------------------------------------------------ clock

    def hold_beat(self) -> float | None:
        if self.mode == "wait" and self.matcher is not None and self.matcher.current is not None:
            return self.matcher.current.beat
        return None

    def _raw_beat(self, t: float) -> float:
        if not self.running:
            return self.anchor_beat
        return self.anchor_beat + (t - self.anchor_t) * self.rate

    def beat_now(self, t: float | None = None) -> float:
        t = self.now() if t is None else t
        with self._lock:
            return self._beat(t)

    def _beat(self, t: float) -> float:
        b = self._raw_beat(t)
        hold = self.hold_beat()
        if hold is not None:
            b = min(b, hold)
        return min(b, self.range_end)

    def _anchor(self, t: float, beat: float) -> None:
        self.anchor_t = t
        self.anchor_beat = beat

    # ------------------------------------------------------------------ controls

    def start(self, song: dict, mode: str = "wait", hands=("R",), speed: float = 1.0,
              section: int | None = None, count_in: bool = True, accompany: bool = True,
              output: str = "mac", breaks: list | None = None, loop: bool | None = None) -> dict:
        if not isinstance(mode, str) or mode not in MODES:
            raise PracticeError("Select Watch or Play.")
        if not isinstance(output, str) or output not in OUTPUTS:
            raise PracticeError("Select the Mac sound or the keyboard speaker.")
        if not isinstance(hands, (list, tuple)) or not all(isinstance(h, str) for h in hands):
            raise PracticeError("Select Right, Left or Both.")
        present = {n["hand"] for n in song["notes"]}
        hands = tuple(h for h in ("R", "L") if h in set(hands))
        if not hands or not set(hands) <= present:
            raise PracticeError("This song has no notes for this hand. Select a different hand.")
        sections = song.get("sections") or []
        if section is not None and not (isinstance(section, int) and not isinstance(section, bool)
                                        and 0 <= section < len(sections)):
            raise PracticeError("The app cannot find this part of the song. Select a different part.")
        msgs = []
        with self._lock:
            msgs = self._all_off()
            self._reset_fields()
            self.song = song
            self.run += 1
            self.mode = mode
            self.hands = hands
            self.speed = clamp_speed(speed)
            self.rate = song["bpm"] * self.speed / 60.0
            if section is None:
                self.range_start, self.range_end = 0.0, song["end"]
            else:
                s = sections[section]
                self.range_start, self.range_end = s["start"], min(s["end"], song["end"])
                # A part repeats ("Repeat Part N"). loop=False (daily session): play the part one time.
                self.section, self.loop = section, loop is not False
            self.count_in = float(song["time_signature"][0]) if count_in else 0.0
            self.accompany = bool(accompany)
            self.output = output
            if mode == "wait":
                self.matcher = WaitMatcher.for_song(song, hands, self.range_start, self.range_end)
                self.breaks = _check_breaks(breaks, self.range_start, self.range_end)
            self._app_notes = self._select_app_notes()
            t = self.now()
            self._anchor(t, self.range_start - self.count_in)
            self._out_i = 0
            self.started_t = t
            self.running = True
            state = self._emit_state(t)
        self._send(msgs)
        self._wake.set()
        return state

    def pause(self, at_beat: float | None = None, reason: str = "user", run: int | None = None) -> dict:
        msgs = []
        with self._lock:
            t = self.now()
            if self.song is not None and self.running and (run is None or run == self.run):
                b = self._beat(t)
                # The UI can ask to go back to the last beat it showed (window hidden: no frames).
                if isinstance(at_beat, (int, float)) and not isinstance(at_beat, bool):
                    low = self.range_start - self.count_in
                    if self.matcher is not None and self.matcher.index > 0:
                        low = max(low, self.matcher.stops[self.matcher.index - 1].beat)
                    if low <= at_beat < b:
                        b = float(at_beat)
                self._anchor(t, b)
                self.running = False
                self.paused = True
                self.pause_reason = reason
                self.waiting = False
                msgs = self._all_off()
                self._out_i = self._first_app_note(b)
            state = self._emit_state(t)
        self._send(msgs)
        return state

    def resume(self) -> dict:
        with self._lock:
            t = self.now()
            if self.song is not None and self.paused and not self.done:
                self._anchor(t, self.anchor_beat)
                self.running = True
                self.paused = False
                self.pause_reason = None
            state = self._emit_state(t)
        self._wake.set()
        return state

    def stop(self) -> dict:
        msgs = []
        with self._lock:
            msgs = self._all_off()
            self.song = None
            self._reset_fields()
            state = self._emit_state(self.now())
        self._send(msgs)
        return state

    def set_speed(self, speed: float) -> dict:
        with self._lock:
            t = self.now()
            if self.song is not None:
                self._anchor(t, self._beat(t))
                self.speed = clamp_speed(speed)
                self.rate = self.song["bpm"] * self.speed / 60.0
            state = self._emit_state(t)
        self._wake.set()
        return state

    # ------------------------------------------------------------------ time passes

    def tick(self, t: float | None = None) -> None:
        msgs = []
        with self._lock:
            t = self.now() if t is None else t
            msgs = self._tick(t)
        self._send(msgs)

    def _tick(self, t: float) -> list:
        if self.song is None or not self.running:
            return []
        raw = self._raw_beat(t)
        hold = self.hold_beat()
        if hold is not None and raw >= hold:
            if not self.waiting:
                self.waiting = True
                self._emit_state(t)
            b = hold
        else:
            b = min(raw, self.range_end)
        if self.breaks and self._break_due(b):
            return msgs_then(self._schedule_output(t, b), self._skill_break(t))
        msgs = self._schedule_output(t, b)
        if hold is None and raw >= self.range_end - EPS:
            if self.loop:
                msgs += self._wrap(t, raw)
            else:
                msgs += self._finish(t)
        return msgs

    def _break_due(self, b: float) -> bool:
        """All stops before the new skill are done and the song is half a beat before it."""
        at, _ = self.breaks[0]
        m = self.matcher
        before_done = m is None or m.current is None or m.current.beat >= at - EPS
        return before_done and b >= at - config.SKILL_BREAK_LEAD_BEATS - EPS

    def _skill_break(self, t: float) -> list:
        at, skill = self.breaks.pop(0)
        b = self._beat(t)
        self._anchor(t, b)
        self.running = False
        self.paused = True
        self.pause_reason = "skill"
        self.waiting = False
        msgs = self._all_off()
        self._out_i = self._first_app_note(b)
        self._emit({"type": "practice_skill", "skill": skill, "beat": at, "song_id": self.song["id"],
                    "run": self.run})
        self._emit_state(t)
        return msgs

    def seek(self, beat: float, run: int | None = None, resume: bool = True) -> dict:
        """Go back to a beat (after a skill moment: "the song continues from just before", PLAN 8.2).
        The song starts LEAD beat before it, so that the user sees the next note fall."""
        msgs = []
        with self._lock:
            t = self.now()
            ok = (self.song is not None and not self.done and (run is None or run == self.run)
                  and isinstance(beat, (int, float)) and not isinstance(beat, bool))
            if ok:
                beat = min(max(float(beat), self.range_start), self.range_end)
                msgs = self._all_off()
                if self.matcher is not None:
                    m = self.matcher
                    m.index = next((i for i, st in enumerate(m.stops) if st.beat >= beat - EPS), len(m.stops))
                    m._presses.clear()
                lead = beat - config.SEEK_LEAD_BEATS  # before the range start = a short silent lead-in
                self._anchor(t, lead)
                self._out_i = self._first_app_note(lead)
                self.waiting = False
                if resume:
                    self.running = True
                    self.paused = False
                    self.pause_reason = None
            state = self._emit_state(t)
        self._send(msgs)
        self._wake.set()
        return state

    def _wrap(self, t: float, raw: float) -> list:
        """Loop a part: start the part again (no count-in)."""
        msgs = self._all_off()
        over = max(0.0, raw - self.range_end)
        self._anchor(t - over / self.rate, self.range_start)
        self.passes += 1
        self.waiting = False
        if self.matcher is not None:
            self.matcher.reset()
        self._out_i = 0
        self._emit_state(t)
        return msgs

    def _finish(self, t: float) -> list:
        msgs = self._all_off()
        self._anchor(t, self.range_end)
        self.running = False
        self.done = True
        self.waiting = False
        m = self.matcher
        stops = len(m.stops) if m is not None else 0
        extra: dict = {"section": self.section, "range": [self.range_start, self.range_end]}
        if m is not None:
            bad = {e["stop"] for e in m.errors}
            clean = stops - len(bad)
            extra.update(clean_stops=clean, accuracy=round(100.0 * clean / stops, 1) if stops else 100.0,
                         errors=[{"beat": m.stops[e["stop"]].beat, "pitch": e["pitch"]} for e in m.errors][:500])
        self._emit({"type": "practice_end", "song_id": self.song["id"], "mode": self.mode, "completed": True,
                    "hands": list(self.hands), "wrong": self.wrong, "stops": stops,
                    "seconds": round(t - self.started_t, 2), "speed": self.speed, "run": self.run, **extra})
        self._emit_state(t)
        return msgs

    # ------------------------------------------------------------------ MIDI input

    def on_midi(self, evt: dict) -> None:
        kind = evt.get("type")
        if kind not in ("note_on", "note_off"):
            return
        with self._lock:
            m = self.matcher
            if self.song is None or m is None:
                return
            pitch = evt["pitch"]
            t = evt.get("t")
            t = self.now() if t is None else t
            if kind == "note_off":
                m.release(pitch, t)
                return
            if not self.running:
                m.release(pitch, t)  # not counted, and not "down" for a later stop either
                return
            b = self._beat(t)
            stop = m.current
            if stop is None or b < self.range_start - EPS:
                m.release(pitch, t)
                return  # song done, or the count-in still runs
            if pitch in stop.pitches and b < stop.beat - config.WAIT_EARLY_BEATS:
                m.release(pitch, t)
                return  # far too early for this note: not wrong, not counted
            res = m.press(pitch, t, b)
            ids = {"song_id": self.song["id"], "run": self.run}
            if res["result"] == "wrong":
                self.wrong += 1
                self._emit({"type": "practice_wrong", "pitch": pitch, "expected": res["expected"],
                            "beat": round(b, 4), "stop": res["stop"], "t": t, **ids})
                return
            if res["result"] != "hit":
                return
            self._emit({"type": "practice_hit", "pitch": pitch, "stop": res["stop"], "t": t, **ids})
            if res["advanced"]:
                if self._raw_beat(t) >= stop.beat:  # the song waited here: go on from now
                    self._anchor(t, stop.beat)
                self.waiting = False
                self._emit_state(t)
        self._wake.set()

    # ------------------------------------------------------------------ keyboard output

    def _select_app_notes(self) -> list[dict]:
        """Notes that the app plays: watch = all; wait = the other hand (if accompany is on)."""
        song = self.song
        assert song is not None
        if self.mode == "watch":
            chosen = song["notes"]
        elif self.accompany:
            chosen = [n for n in song["notes"] if n["hand"] not in self.hands]
        else:
            chosen = []
        return [n for n in chosen if self.range_start - EPS <= n["start"] < self.range_end - EPS]

    def _first_app_note(self, beat: float) -> int:
        for i, n in enumerate(self._app_notes):
            if n["start"] >= beat - EPS:
                return i
        return len(self._app_notes)

    def _schedule_output(self, t: float, beat: float) -> list:
        if self.output != "keyboard" or self.midi is None:
            return []
        msgs = []
        still = []
        for off_t, pitch in self._sounding:
            if off_t <= t:
                msgs.append(self.midi.note_message(pitch, 0))
            else:
                still.append((off_t, pitch))
        self._sounding = still
        notes = self._app_notes
        while self._out_i < len(notes) and notes[self._out_i]["start"] < beat - EPS:
            n = notes[self._out_i]
            self._out_i += 1
            msgs.append(self.midi.note_message(n["pitch"], n["vel"]))
            self._sounding.append((t + n["dur"] / self.rate * 0.95, n["pitch"]))
        return msgs

    def _all_off(self) -> list:
        if self.midi is None or not self._sounding:
            self._sounding = []
            return []
        msgs = [self.midi.note_message(p, 0) for _, p in self._sounding]
        self._sounding = []
        return msgs

    def _send(self, msgs: list) -> None:
        """Send MIDI out after the lock is released (the MIDI thread can call on_midi)."""
        for msg in msgs:
            try:
                if msg.type == "note_on" and msg.velocity > 0:
                    self.echo.sent(msg.note, self.now())  # before the send: the echo can come fast
                self.midi.send(msg)
            except Exception:
                log.exception("Cannot send a song note to the keyboard")

    # ------------------------------------------------------------------ state

    def _emit(self, evt: dict) -> None:
        self.sink(evt)

    def _emit_state(self, t: float) -> dict:
        state = self._state(t)
        self.sink(state)
        return state

    def state(self) -> dict:
        with self._lock:
            return self._state(self.now(), bump=False)

    def _state(self, t: float, bump: bool = True) -> dict:
        if bump:
            self.seq += 1
        if self.song is None:
            return {"type": "practice", "seq": self.seq, "t": t, "song_id": None, "running": False,
                    "paused": False, "done": False}
        m = self.matcher
        stop = m.current if m is not None else None
        return {
            "type": "practice", "seq": self.seq, "t": t, "run": self.run,
            "song_id": self.song["id"], "title": self.song["title"], "mode": self.mode,
            "hands": list(self.hands), "speed": self.speed, "bpm": self.song["bpm"], "rate": self.rate,
            "running": self.running, "paused": self.paused, "pause_reason": self.pause_reason,
            "done": self.done, "anchor_t": self.anchor_t, "anchor_beat": self.anchor_beat,
            "beat": self._beat(t), "hold_beat": self.hold_beat(), "waiting": self.waiting,
            "stop_index": m.index if m is not None else None,
            "stop_count": len(m.stops) if m is not None else None,
            "expected": [{"pitch": n["pitch"], "hand": n["hand"], "finger": n["finger"]}
                         for n in stop.notes] if stop is not None else [],
            "range": [self.range_start, self.range_end], "section": self.section, "loop": self.loop,
            "count_in": self.count_in, "passes": self.passes, "wrong": self.wrong,
            "accompany": self.accompany, "output": self.output,
        }


def msgs_then(a: list, b: list) -> list:
    return a + b


def _check_breaks(breaks, start: float, end: float) -> list[tuple[float, str]]:
    """Skill moments inside the range (a skill at the start is shown before the song starts)."""
    out = []
    for b in breaks or []:
        if not isinstance(b, dict):
            continue
        at, skill = b.get("beat"), b.get("skill")
        if isinstance(at, (int, float)) and not isinstance(at, bool) and isinstance(skill, str) \
                and start + EPS < at < end - EPS:
            out.append((float(at), skill[:64]))
    return sorted(out)


def clamp_speed(speed: Any) -> float:
    try:
        s = float(speed)
    except (TypeError, ValueError):
        s = 1.0
    if s != s:  # NaN
        s = 1.0
    return min(config.SPEED_MAX, max(config.SPEED_MIN, s))
