"""MIDI service: ports, hot-plug, events, calibration, output.

Threads:
- The rtmidi callback runs on a CoreMIDI thread. It stamps clock.now() first, then calls
  ``sink(event)``. The server makes ``sink`` thread-safe (loop.call_soon_threadsafe).
- One MIDI thread owns ALL CoreMIDI calls (list, open, close, send) and checks the port
  list every ``poll_interval`` seconds (hot-plug). Other threads hand work to it (_call).
  Reason (tested in Phase 1): CoreMIDI updates the port list only for the thread that
  made the process's first CoreMIDI client. A port list from any other thread stays old,
  so a keyboard plugged in later is never seen. See DECISIONS.md.

YPT-320 rules (RESEARCH.md section 4):
- It sends Note On velocity 0 for note off.
- In PC mode OFF it also sends style/song notes, MIDI clock, start/stop, sysex and program
  changes. Only note_on, note_off and CC 64 pass. After calibration, only the calibrated
  channel passes.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future
from collections.abc import Callable
from typing import Any

import mido

from . import clock, config, theory
from .db import Store

log = logging.getLogger("riyaz.midi")

Event = dict[str, Any]
Sink = Callable[[Event], None]

CAPTURE_MODES = ("test", "middle_c", "touch")


def _backend():
    # Name the backend explicitly. PyInstaller needs --hidden-import mido.backends.rtmidi.
    return mido.Backend("mido.backends.rtmidi", load=True)


class MidiService:
    def __init__(self, store: Store, sink: Sink | None = None,
                 poll_interval: float = config.HOTPLUG_INTERVAL_S, backend=None,
                 port_filter: str | None = None):
        self.store = store
        self.sink: Sink = sink or (lambda evt: None)
        self.poll_interval = poll_interval
        self.backend = backend or _backend()
        # Only ports whose name starts with this prefix (tests: see only the virtual port).
        self.port_filter = port_filter if port_filter is not None else config.port_filter()

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._tasks: queue.Queue = queue.Queue()
        self._stopping = False
        # Test-note timers -> the note_off they send (stop() sends them at once).
        self._pending_offs: dict[threading.Timer, mido.Message] = {}

        self._inport = None
        self._outport = None
        self.port_name: str | None = None
        self.inputs: list[str] = []
        self.outputs: list[str] = []

        # Calibration (stored).
        self.offset: int = int(store.get("calibration.offset", 0))
        self.channel: int | None = store.get("calibration.channel", None)
        self.velocity_range: list[int] | None = store.get("calibration.velocity_range", None)

        self.capture_mode: str | None = None
        self._touch_samples: list[int] = []

        self.held: dict[tuple[int, int], int] = {}  # (channel, raw pitch) -> calibrated pitch
        self.sustain = False
        self.local_off = False

    # ------------------------------------------------------------------ life cycle

    def start(self) -> None:
        """Start the MIDI thread. Returns after the first port scan."""
        self._stop.clear()
        self._stopping = False
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(ready,), name="riyaz-midi", daemon=True)
        self._thread.start()
        ready.wait(10)

    def stop(self) -> None:
        self._stopping = True
        if self._thread is not None and self._thread.is_alive():
            try:
                self._call(self._shutdown)
            finally:
                self._stop.set()
                self._tasks.put(None)
                self._thread.join(timeout=5)
        else:
            self._shutdown()
        self._thread = None

    def _shutdown(self) -> None:
        with self._lock:
            # Test note still sounding: cancel its timer and send its note_off now.
            pending, self._pending_offs = self._pending_offs, {}
            for timer, off in pending.items():
                timer.cancel()
                try:
                    self._send(off)
                except Exception:
                    log.exception("Cannot send test note off")
            if self.local_off:
                self._set_local_control(True)
            self._close_input(emit=False)
            self._close_output()

    def _run(self, ready: threading.Event) -> None:
        try:
            self._scan(True)  # makes the first CoreMIDI client on THIS thread
        except Exception:
            log.exception("MIDI port scan failed")
        finally:
            ready.set()
        next_scan = time.monotonic() + self.poll_interval
        while not self._stop.is_set():
            try:
                task = self._tasks.get(timeout=max(0.0, next_scan - time.monotonic()))
            except queue.Empty:
                try:
                    self._scan(True)
                except Exception:  # never let the MIDI thread die
                    log.exception("MIDI port scan failed")
                next_scan = time.monotonic() + self.poll_interval
                continue
            if task is None:
                break
            fn, args, fut = task
            try:
                fut.set_result(fn(*args))
            except BaseException as exc:
                fut.set_exception(exc)

    def _call(self, fn, *args):
        """Run fn on the MIDI thread (or here, if the thread does not run: unit tests)."""
        t = self._thread
        if t is None or not t.is_alive() or threading.current_thread() is t:
            return fn(*args)
        fut: Future = Future()
        self._tasks.put((fn, args, fut))
        return fut.result(timeout=10)

    # ------------------------------------------------------------------ ports

    def _list_ports(self) -> tuple[list[str], list[str]]:
        inputs, outputs = list(self.backend.get_input_names()), list(self.backend.get_output_names())
        if self.port_filter:
            inputs = [n for n in inputs if n.startswith(self.port_filter)]
            outputs = [n for n in outputs if n.startswith(self.port_filter)]
        return inputs, outputs

    @property
    def connected(self) -> bool:
        return self._inport is not None

    def status(self) -> Event:
        return {
            "type": "status",
            "connected": self.connected,
            "port": self.port_name,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "output": self._output_name(),
            "remembered": self.store.get("midi.input", None),
            "calibration": self.calibration(),
        }

    def calibration(self) -> Event:
        return {
            "offset": self.offset,
            "channel": None if self.channel is None else self.channel + 1,  # 1-16 for people
            "velocity_range": self.velocity_range,
            "calibrated": self.store.get("calibration.offset", None) is not None,
        }

    def scan(self, auto_pick: bool = True) -> Event:
        """Check the port list. Handle unplug and plug-in. Return the status."""
        return self._call(self._scan, auto_pick)

    def _scan(self, auto_pick: bool) -> Event:
        inputs, outputs = self._list_ports()
        with self._lock:
            changed = inputs != self.inputs or outputs != self.outputs
            self.inputs, self.outputs = inputs, outputs
            if self.port_name is not None and self.port_name not in inputs:
                log.info("Keyboard disconnected: %s", self.port_name)
                self._close_input(emit=True)
                self._close_output()
                changed = True
            if self._inport is None and auto_pick:
                choice = self._auto_choice(inputs)
                if choice is not None and self._open_input(choice):
                    changed = True
            status = self.status()
        if changed:
            self.sink(status)
        return status

    def _auto_choice(self, inputs: list[str]) -> str | None:
        remembered = self.store.get("midi.input", None)
        if remembered in inputs:
            return remembered
        candidates = [n for n in inputs if not n.startswith(config.IGNORED_PORT_PREFIXES)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    def select_port(self, name: str) -> Event:
        """The user picked a port in the setup screen."""
        return self._call(self._select_port, name)

    def _select_port(self, name: str) -> Event:
        inputs, outputs = self._list_ports()
        with self._lock:
            self.inputs, self.outputs = inputs, outputs
            if name not in inputs:
                raise ValueError(f"Port not found: {name}")
            if self.port_name != name:
                self._close_input(emit=True)
                self._close_output()
                self._open_input(name)
            self.store.set("midi.input", name)
            status = self.status()
        self.sink(status)
        return status

    def find_keyboard(self) -> Event:
        """'Find my keyboard' button: scan now and pick automatically."""
        status = self.scan(auto_pick=True)
        self.sink(status)  # always answer, also when nothing changed
        return status

    def _open_input(self, name: str) -> bool:
        try:
            port = self.backend.open_input(name, callback=self._on_message)
        except (OSError, RuntimeError) as exc:
            log.warning("Cannot open MIDI input %r: %s", name, exc)
            return False
        self._inport = port
        self.port_name = name
        if self.store.get("midi.input", None) is None:
            self.store.set("midi.input", name)  # remember the automatic choice
        log.info("Keyboard connected: %s", name)
        if self.store.get("midi.local_off_pending", False):
            # The app stopped last time with Local Off set. Turn the keyboard sound on again.
            self._set_local_control(True)
        return True

    def _close_input(self, emit: bool) -> None:
        port, self._inport = self._inport, None
        self.port_name = None
        if port is not None:
            try:
                port.close()
            except Exception:
                log.exception("Cannot close MIDI input")
        if emit:
            self._release_all()

    def _release_all(self) -> None:
        """Cable pulled or port changed: send 'all keys up' so that no key stays lit."""
        t = clock.now()
        held, self.held = self.held, {}
        for (ch, raw), pitch in held.items():
            self.sink({"type": "note_off", "pitch": pitch, "raw": raw, "ch": ch + 1, "t": t, "reason": "disconnect"})
        if held:
            self.sink(self.keys_event())
        if self.sustain:
            self.sustain = False
            self.sink({"type": "cc", "control": config.SUSTAIN_CC, "value": 0, "ch": (self.channel or 0) + 1, "t": t,
                       "reason": "disconnect"})

    # ------------------------------------------------------------------ output

    def _output_name(self) -> str | None:
        """Output port for the keyboard: same name as the input (USB-MIDI cables do this)."""
        if self.port_name and self.port_name in self.outputs:
            return self.port_name
        return None

    def _get_output(self):
        name = self._output_name()
        if name is None:
            return None
        if self._outport is None or self._outport.name != name:
            self._close_output()
            try:
                self._outport = self.backend.open_output(name)
            except (OSError, RuntimeError) as exc:
                log.warning("Cannot open MIDI output %r: %s", name, exc)
                self._outport = None
        return self._outport

    def _close_output(self) -> None:
        port, self._outport = self._outport, None
        if port is not None:
            try:
                port.close()
            except Exception:
                log.exception("Cannot close MIDI output")

    def send(self, msg: mido.Message) -> bool:
        if self._stopping:
            return False  # after stop(): do not open the output port again
        return self._call(self._send, msg)

    def _send(self, msg: mido.Message) -> bool:
        with self._lock:
            out = self._get_output()
            if out is None:
                return False
            out.send(msg)
            return True

    def play_test_note(self, pitch: int = config.MIDDLE_C, velocity: int = 90, seconds: float = 0.8) -> bool:
        """Setup step 5: play a note on the keyboard's own speaker."""
        ch = self.channel or 0
        raw = pitch - self.offset
        if not 0 <= raw <= 127:
            raw = pitch
        off = mido.Message("note_on", note=raw, velocity=0, channel=ch)
        timer = threading.Timer(seconds, self._test_note_off)
        timer.args = (off, timer)
        timer.daemon = True  # never keeps the app alive
        with self._lock:
            if self._stopping:
                return False
            self._pending_offs[timer] = off  # registered first: stop() sends it if it comes first
        if not self.send(mido.Message("note_on", note=raw, velocity=velocity, channel=ch)):
            with self._lock:
                self._pending_offs.pop(timer, None)
            return False
        timer.start()
        return True

    def _test_note_off(self, off: mido.Message, timer: threading.Timer) -> None:
        with self._lock:
            if self._pending_offs.pop(timer, None) is None:
                return  # stop() sent it already
        self._send_quietly(off)

    def _send_quietly(self, msg: mido.Message) -> None:
        try:
            self.send(msg)
        except Exception:
            log.exception("Cannot send MIDI message")

    def set_local_control(self, on: bool) -> bool:
        """CC 122. Off = the keyboard makes no sound (Mac sound only). Always On again at exit."""
        return self._call(self._set_local_control, on)

    def _set_local_control(self, on: bool) -> bool:
        ch = self.channel or 0
        sent = self._send(mido.Message("control_change", control=config.LOCAL_CONTROL_CC,
                                      value=127 if on else 0, channel=ch))
        if sent:
            self.local_off = not on
            self.store.set("midi.local_off_pending", not on)
        return sent

    # ------------------------------------------------------------------ calibration

    def start_capture(self, mode: str) -> None:
        if mode not in CAPTURE_MODES:
            raise ValueError(f"Unknown setup step: {mode}")
        with self._lock:
            self.capture_mode = mode
            self._touch_samples = []

    def cancel_capture(self) -> None:
        with self._lock:
            self.capture_mode = None
            self._touch_samples = []

    def set_calibration(self, offset: int, channel: int | None) -> None:
        with self._lock:
            self.offset = int(offset)
            self.channel = channel
            self.store.set("calibration.offset", self.offset)
            self.store.set("calibration.channel", channel)

    def reset_calibration(self) -> None:
        with self._lock:
            self.offset = 0
            self.channel = None
            self.velocity_range = None
            for key in ("calibration.offset", "calibration.channel", "calibration.velocity_range"):
                self.store.delete(key)
        self.sink({"type": "calibration", "step": "reset", **self.calibration()})

    # ------------------------------------------------------------------ input

    def _on_message(self, msg: mido.Message) -> None:
        self.handle_message(msg, clock.now())

    def handle_message(self, msg: mido.Message, t: float | None = None) -> Event | None:
        """Turn one MIDI message into a UI event (or drop it). Public for tests."""
        if t is None:
            t = clock.now()
        kind = msg.type
        if kind not in ("note_on", "note_off", "control_change"):
            return None  # clock, start, stop, sysex, program_change, active sensing, ...
        if kind == "control_change" and msg.control != config.SUSTAIN_CC:
            return None

        out: list[Event] = []
        with self._lock:
            mode = self.capture_mode
            is_press = kind == "note_on" and msg.velocity > 0
            # A key that is down (in self.held) always gets its note_off, on any channel.
            # If not, a key pressed before the channel was known stays lit forever.
            releases_held = kind != "control_change" and not is_press and (msg.channel, msg.note) in self.held

            # Channel filter. Exceptions: the release of a held key, and the middle C step
            # (it finds the channel). The "test" step uses the known channel, if there is one.
            if (self.channel is not None and msg.channel != self.channel and not releases_held
                    and not (mode == "middle_c" and is_press)):
                return None  # style/song/dual/split notes on other channels

            if mode in ("test", "middle_c") and is_press:
                self.capture_mode = None
                if mode == "test":
                    out.append({"type": "setup", "step": "test", "ok": True, "raw": msg.note,
                                "ch": msg.channel + 1, "t": t})
                else:
                    self.set_calibration(config.MIDDLE_C - msg.note, msg.channel)
                    out.append({"type": "calibration", "step": "middle_c", "raw": msg.note, **self.calibration()})

            evt = self._to_event(msg, t)
            if evt is not None and evt["type"] != "cc":
                out.insert(0, self.keys_event())
            if evt is not None and mode == "touch" and evt["type"] == "note_on":
                out.extend(self._touch_sample(evt["vel"]))
        if evt is not None:
            self.sink(evt)
        for extra in out:
            self.sink(extra)
        return evt

    def keys_event(self) -> Event:
        """Keys that are down now, with their names and the chord name (free play)."""
        held = sorted(set(self.held.values()))
        return {"type": "keys", "held": held, "names": [theory.note_name(p) for p in held],
                "chord": theory.detect_chord(held)}

    def _to_event(self, msg: mido.Message, t: float) -> Event | None:
        ch = msg.channel
        if msg.type == "control_change":
            self.sustain = msg.value >= 64
            return {"type": "cc", "control": msg.control, "value": msg.value, "ch": ch + 1, "t": t}
        raw = msg.note
        if msg.type == "note_on" and msg.velocity > 0:
            pitch = raw + self.offset
            if not 0 <= pitch <= 127:
                return None
            self.held[(ch, raw)] = pitch
            return {"type": "note_on", "pitch": pitch, "raw": raw, "vel": msg.velocity, "ch": ch + 1, "t": t}
        # note_off, or note_on with velocity 0 (the YPT-320 sends this)
        pitch = self.held.pop((ch, raw), raw + self.offset)
        if not 0 <= pitch <= 127:
            return None
        return {"type": "note_off", "pitch": pitch, "raw": raw, "ch": ch + 1, "t": t}

    def _touch_sample(self, velocity: int) -> list[Event]:
        self._touch_samples.append(velocity)
        n = len(self._touch_samples)
        if n < config.TOUCH_SAMPLE_COUNT:
            return [{"type": "calibration", "step": "touch_progress", "count": n,
                     "needed": config.TOUCH_SAMPLE_COUNT}]
        samples, self._touch_samples = self._touch_samples, []
        self.capture_mode = None
        low, high = min(samples), max(samples)
        touch_on = high - low >= config.TOUCH_MIN_SPREAD
        if touch_on:
            self.velocity_range = [low, high]
            self.store.set("calibration.velocity_range", self.velocity_range)
        return [{"type": "calibration", "step": "touch", "touch_on": touch_on, "samples": samples,
                 **self.calibration()}]
