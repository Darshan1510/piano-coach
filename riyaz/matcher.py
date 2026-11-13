"""Wait-mode matcher (PLAN 6.4).

- A stop point = one start time (beat) in the song. Its expected set = all notes that start at
  this time, for the active hands.
- The song continues when all expected keys are down at the same time (keys together), or were
  pressed in order within 300 ms (config.WAIT_CHORD_WINDOW_S).
- A wrong key (not in the expected set) does not continue the song. It is logged.

Only presses after a stop became the current stop count: a key that repeats (E E E) must be
pressed again. This module has no clock and no MIDI: tests feed it events directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config

EPS = 1e-6


@dataclass(frozen=True)
class Stop:
    index: int
    beat: float
    pitches: frozenset[int]
    notes: tuple[dict, ...]


@dataclass
class WaitMatcher:
    stops: list[Stop]
    window: float = config.WAIT_CHORD_WINDOW_S
    index: int = 0
    errors: list[dict] = field(default_factory=list)
    _presses: dict[int, float] = field(default_factory=dict)  # pitch -> press time (current stop)
    _down: set[int] = field(default_factory=set)

    @classmethod
    def for_song(cls, song: dict, hands, start: float | None = None, end: float | None = None,
                 window: float = config.WAIT_CHORD_WINDOW_S) -> "WaitMatcher":
        return cls(stops=build_stops(song, hands, start, end), window=window)

    @property
    def current(self) -> Stop | None:
        return self.stops[self.index] if self.index < len(self.stops) else None

    @property
    def done(self) -> bool:
        return self.index >= len(self.stops)

    def reset(self) -> None:
        self.index = 0
        self._presses.clear()

    def press(self, pitch: int, t: float, beat: float | None = None) -> dict:
        """A key went down. Returns {"result": "hit" | "wrong" | "done", "advanced": bool, ...}."""
        self._down.add(pitch)
        stop = self.current
        if stop is None:
            return {"result": "done", "advanced": False}
        if pitch not in stop.pitches:
            err = {"stop": stop.index, "pitch": pitch, "expected": sorted(stop.pitches), "t": t, "beat": beat}
            self.errors.append(err)
            return {"result": "wrong", "advanced": False, "stop": stop.index, "expected": sorted(stop.pitches)}
        self._presses[pitch] = t
        if self._complete(t):
            self.index += 1
            self._presses.clear()
            return {"result": "hit", "advanced": True, "stop": stop.index}
        return {"result": "hit", "advanced": False, "stop": stop.index}

    def release(self, pitch: int, t: float) -> None:
        self._down.discard(pitch)

    def _complete(self, t: float) -> bool:
        stop = self.current
        assert stop is not None
        for p in stop.pitches:
            pt = self._presses.get(p)
            if pt is None:
                return False
            # Down now (keys together), or pressed in order within the window.
            if p not in self._down and t - pt > self.window + EPS:
                return False
        return True


def build_stops(song: dict, hands, start: float | None = None, end: float | None = None) -> list[Stop]:
    """Stop points for the active hands, in the beat range [start, end)."""
    hands = set(hands)
    groups: dict[float, list[dict]] = {}
    for n in song["notes"]:
        if n["hand"] not in hands:
            continue
        if start is not None and n["start"] < start - EPS:
            continue
        if end is not None and n["start"] >= end - EPS:
            continue
        key = round(n["start"], 6)
        groups.setdefault(key, []).append(n)
    stops = []
    for i, beat in enumerate(sorted(groups)):
        notes = tuple(sorted(groups[beat], key=lambda n: n["pitch"]))
        stops.append(Stop(index=i, beat=beat, pitches=frozenset(n["pitch"] for n in notes), notes=notes))
    return stops
