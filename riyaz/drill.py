"""Drills: short key checks on the real keyboard (keyboard basics, skill moments, warm-up,
"Find the key"). PLAN 8.1, 8.2, 9.1, 10.

A drill gets MIDI events (after the calibration offset) from the server sink. It knows what to
expect and sends ``drill`` events with the state, so that the UI (and the fake player) can show
or play the expected keys.

Kinds:
- ``collect``: press every key of a set, in any order ("Press every C").
- ``steps``:   a list of steps, ``tries`` times. A step is ``{"any": [pitches]}`` (one of these
  keys; ``null`` = any key) or ``{"all": [pitches]}`` (these keys together, or in order within
  300 ms). Options: ``hold`` (seconds to hold the key down), ``rest`` (seconds with no key down
  before this step), ``vel`` ("soft" or "loud"), ``finger``/``hand`` (for the screen).
  With tries > 1 (skill moments), a mistake starts the try again. With 1 try, the step waits.
- ``find_key``: ``rounds`` rounds; each round names a white key ("Play F"); any octave counts.

Events: ``drill`` (full state, after each change), ``drill_hit``, ``drill_wrong`` {pitch, reason}.
reasons: "wrong_key", "too_short" (held less than ``hold``), "too_early" (pressed in the
pause), "too_soft", "too_loud".
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Callable

from . import clock, config

log = logging.getLogger("riyaz.drill")

WHITE_NAMES = {0: "C", 2: "D", 4: "E", 5: "F", 7: "G", 9: "A", 11: "B"}
KINDS = ("collect", "steps", "find_key")


class DrillError(ValueError):
    """The text is for the user."""


def keys_of_class(pc: int, low: int = config.KEY_LOW, high: int = config.KEY_HIGH) -> list[int]:
    return [p for p in range(low, high + 1) if p % 12 == pc]


class Drill:
    def __init__(self, sink: Callable[[dict], None], now: Callable[[], float] = clock.now,
                 vel_split: Callable[[], int] | None = None):
        self.sink = sink
        self.now = now
        self.vel_split = vel_split or (lambda: 64)
        self._lock = threading.RLock()
        self.seq = 0
        self.run = 0
        self.spec: dict | None = None
        self.on_pass: Callable[[dict, dict], dict | None] | None = None
        self._reset()

    def _reset(self) -> None:
        self.status = "idle"  # idle | active | passed | stopped
        self.try_i = 0
        self.tries_ok = 0
        self.step_i = 0
        self.wrong = 0
        self.fails = 0
        self.collected: set[int] = set()
        self.round_i = 0
        self.target: int | None = None
        self.round_t = 0.0
        self.times: list[float] = []
        self.started_t = 0.0
        self.result: dict = {}
        self.last = ""
        self._down: dict[int, float] = {}  # pitch -> press time
        self._presses: dict[int, float] = {}  # pitches of the current "all" step -> press time
        self._hold: tuple[int, float] | None = None  # (pitch, press time) of a step that needs a hold
        self._last_up = None  # time when the last key went up
        self._rng = random.Random()

    # ------------------------------------------------------------------ control

    def start(self, spec: dict, on_pass: Callable[[dict, dict], dict | None] | None = None,
              seed: int | None = None) -> dict:
        spec = self._check(spec)
        with self._lock:
            self._reset()
            if seed is not None:
                self._rng.seed(seed)
            self.run += 1
            self.spec = spec
            self.on_pass = on_pass
            self.status = "active"
            self.started_t = self.now()
            if spec["kind"] == "find_key":
                self._next_round(self.started_t)
            return self._emit_state()

    def stop(self) -> dict:
        with self._lock:
            if self.status == "active":
                self.status = "stopped"
            return self._emit_state()

    def state(self) -> dict:
        with self._lock:
            return self._state(bump=False)

    @staticmethod
    def _check(spec: dict) -> dict:
        if not isinstance(spec, dict) or spec.get("kind") not in KINDS:
            raise DrillError("The app does not know this exercise.")
        spec = dict(spec)
        spec.setdefault("id", spec["kind"])
        spec["tries"] = int(spec.get("tries", 1) or 1)
        if spec["kind"] == "collect":
            pitches = spec.get("pitches")
            if not isinstance(pitches, list) or not pitches:
                raise DrillError("The app does not know this exercise.")
        elif spec["kind"] == "steps":
            steps = spec.get("steps")
            if not isinstance(steps, list) or not steps:
                raise DrillError("The app does not know this exercise.")
        else:
            spec["rounds"] = max(1, int(spec.get("rounds", config.FIND_KEY_ROUNDS)))
            choices = spec.get("choices") or sorted(WHITE_NAMES)
            spec["choices"] = [c for c in choices if c in WHITE_NAMES] or sorted(WHITE_NAMES)
        return spec

    # ------------------------------------------------------------------ MIDI input

    def on_midi(self, evt: dict) -> None:
        kind = evt.get("type")
        if kind not in ("note_on", "note_off"):
            return
        with self._lock:
            if self.status != "active" or self.spec is None:
                return
            pitch = evt["pitch"]
            t = evt.get("t")
            t = self.now() if t is None else t
            if kind == "note_off":
                self._release(pitch, t)
                return
            self._down[pitch] = t
            k = self.spec["kind"]
            if k == "collect":
                self._collect(pitch, t)
            elif k == "steps":
                self._step_press(pitch, evt.get("vel", 80), t)
            else:
                self._find(pitch, t)

    def _release(self, pitch: int, t: float) -> None:
        self._down.pop(pitch, None)
        if not self._down:
            self._last_up = t
        if self._hold and self._hold[0] == pitch:
            p, t0 = self._hold
            self._hold = None
            need = float(self._step().get("hold", 0))
            if t - t0 + 1e-6 >= need:
                self._advance(t)
            else:
                self._fail(pitch, "too_short", t)

    # ---- collect

    def _collect(self, pitch: int, t: float) -> None:
        want = set(self.spec["pitches"])
        if pitch not in want:
            self.wrong += 1
            self._wrong(pitch, "wrong_key")
            return
        if pitch in self.collected:
            return
        self.collected.add(pitch)
        self._emit({"type": "drill_hit", "pitch": pitch, "run": self.run, "id": self.spec["id"]})
        if self.collected >= want:
            self._pass(t)
        else:
            self.last = "hit"
            self._emit_state()

    # ---- steps

    def _step(self) -> dict:
        return self.spec["steps"][self.step_i]

    def _step_press(self, pitch: int, vel: int, t: float) -> None:
        step = self._step()
        if self._hold is not None:
            return  # a key of a long note is down: other keys wait for its release (not wrong)
        rest = float(step.get("rest", 0) or 0)
        if rest and (len(self._down) > 1 or self._last_up is None or t - self._last_up + 1e-6 < rest):
            self._fail(pitch, "too_early", t)
            return
        keys = step.get("all") or step.get("any")
        if keys is not None and pitch not in keys:
            self._fail(pitch, "wrong_key", t)
            return
        want = step.get("vel")
        if want:
            split = self.vel_split()
            if want == "soft" and vel >= split:
                self._fail(pitch, "too_loud", t)
                return
            if want == "loud" and vel < split:
                self._fail(pitch, "too_soft", t)
                return
        self._emit({"type": "drill_hit", "pitch": pitch, "run": self.run, "id": self.spec["id"]})
        if step.get("all"):
            self._presses[pitch] = t
            if all(p in self._presses and (p in self._down or t - self._presses[p] <= config.WAIT_CHORD_WINDOW_S + 1e-6)
                   for p in step["all"]):
                self._advance(t)
            else:
                self.last = "hit"
                self._emit_state()
            return
        if step.get("hold"):
            self._hold = (pitch, t)
            self.last = "hold"
            self._emit_state()
            return
        self._advance(t)

    def _advance(self, t: float) -> None:
        self._presses.clear()
        self.step_i += 1
        if self.step_i < len(self.spec["steps"]):
            self.last = "hit"
            self._emit_state()
            return
        self.tries_ok += 1
        self.try_i += 1
        self.step_i = 0
        if self.tries_ok >= self.spec["tries"]:
            self._pass(t)
        else:
            self.last = "try_ok"
            self._emit_state()

    def _fail(self, pitch: int, reason: str, t: float) -> None:
        self.wrong += 1
        self._hold = None
        self._presses.clear()
        if self.spec["tries"] > 1 and self.step_i > 0:
            self.fails += 1
            self.try_i += 1
            self.step_i = 0  # start this try again from the first key
        self._wrong(pitch, reason)

    # ---- find the key

    def _next_round(self, t: float) -> None:
        choices = [c for c in self.spec["choices"] if self.target is None or c != self.target % 12] or self.spec["choices"]
        pc = self._rng.choice(choices)
        self.target = pc
        self.round_t = t

    def _find(self, pitch: int, t: float) -> None:
        if self.target is None or pitch % 12 != self.target:
            self.wrong += 1
            self._wrong(pitch, "wrong_key")
            return
        self.times.append(round(t - self.round_t, 3))
        self._emit({"type": "drill_hit", "pitch": pitch, "run": self.run, "id": self.spec["id"]})
        self.round_i += 1
        if self.round_i >= self.spec["rounds"]:
            self.target = None
            self._pass(t)
            return
        self._next_round(t)
        self.last = "hit"
        self._emit_state()

    # ------------------------------------------------------------------ results

    def _wrong(self, pitch: int, reason: str) -> None:
        self.last = reason
        self._emit({"type": "drill_wrong", "pitch": pitch, "reason": reason, "run": self.run, "id": self.spec["id"]})
        self._emit_state()

    def _pass(self, t: float) -> None:
        self.status = "passed"
        self.last = "passed"
        summary = {"id": self.spec["id"], "kind": self.spec["kind"], "wrong": self.wrong, "fails": self.fails,
                   "seconds": round(t - self.started_t, 2), "times": list(self.times),
                   "tries": self.tries_ok, "source": self.spec.get("source"), "ref": self.spec.get("ref")}
        self.result = summary
        if self.on_pass is not None:
            try:
                extra = self.on_pass(self.spec, summary)
                if extra:
                    self.result = {**summary, **extra}
            except Exception:
                log.exception("Drill result could not be saved")
        self._emit_state()

    # ------------------------------------------------------------------ state

    def _emit(self, evt: dict) -> None:
        self.sink(evt)

    def _emit_state(self) -> dict:
        s = self._state()
        self.sink(s)
        return s

    def _state(self, bump: bool = True) -> dict:
        if bump:
            self.seq += 1
        spec = self.spec
        base = {"type": "drill", "seq": self.seq, "run": self.run, "status": self.status}
        if spec is None:
            return base
        base.update(id=spec["id"], kind=spec["kind"], source=spec.get("source"), ref=spec.get("ref"),
                    wrong=self.wrong, last=self.last, tries=spec["tries"], tries_ok=self.tries_ok,
                    try_index=self.try_i, vel_split=self.vel_split(), result=self.result or None)
        if spec["kind"] == "collect":
            base.update(pitches=spec["pitches"], collected=sorted(self.collected),
                        expect={"any": sorted(set(spec["pitches"]) - self.collected)})
        elif spec["kind"] == "steps":
            base.update(steps=spec["steps"], step=self.step_i, step_count=len(spec["steps"]),
                        expect=dict(self._step()) if self.status == "active" else None,
                        holding=self._hold is not None)
        else:
            base.update(round=self.round_i, rounds=spec["rounds"], times=list(self.times),
                        target=({"name": WHITE_NAMES[self.target], "pc": self.target,
                                 "pitches": keys_of_class(self.target)} if self.target is not None else None),
                        expect={"any": keys_of_class(self.target)} if self.target is not None else None)
        return base
