"""Free-play recorder (PLAN 3 "Advanced", Phase 6): record, play back, export to a MIDI file.

- Record: the keys (after the calibration offset, as the app shows them) and the foot switch
  (MIDI CC 64, when the keyboard sends it) from the server sink, with their times.
- Save: <data dir>/recordings/<id>.json and its summary in recordings/index.json (the list reads
  only the index). Both are in the app data folder (RIYAZ_DATA_DIR in tests; never the
  project folder). A recording stops by itself after MAX_SECONDS or MAX_EVENTS.
- Play back: on the Mac (the page plays the events with Tone.js), or, only when the user selects
  it, on the keyboard speaker (this module sends the notes; the echo guard of riyaz/practice.py
  drops the notes that come back).
- Export: a standard MIDI file (type 0, 120 clicks a minute, 480 ticks per click) with mido. The
  file is also written next to the recording (<id>.mid). The MIDI importer
  (riyaz/importers/midi_import.py) can read it back as a song.

Events: ``recorder`` (the state after each change).
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path

import mido

from . import clock, config

log = logging.getLogger("riyaz.recorder")

MAX_SECONDS = 30 * 60
MAX_EVENTS = 50_000
KEEP_MAX = 200  # recordings in the folder (the oldest goes when a new one is saved)
TEMPO_US = 500_000  # 120 clicks a minute
TICKS = 480
_ID_RE = re.compile(r"^rec-[0-9]{8}-[0-9]{6}(?:-[0-9]+)?$")


class RecorderError(ValueError):
    """The text is for the user."""


def folder() -> Path:
    return config.data_dir() / "recordings"


def _path(rec_id: str, ext: str = ".json") -> Path:
    if not isinstance(rec_id, str) or not _ID_RE.match(rec_id):
        raise RecorderError("The app cannot find this recording.")
    return folder() / f"{rec_id}{ext}"


def to_midi(rec: dict) -> bytes:
    """A standard MIDI file of the recording (type 0, one track)."""
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("track_name", name=str(rec.get("title", "Recording"))[:60], time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=TEMPO_US, time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    ticks_per_s = TICKS * 1_000_000 / TEMPO_US
    last = 0
    down: set[int] = set()
    for t, kind, a, b in rec["events"]:
        tick = max(last, int(round(float(t) * ticks_per_s)))
        delta, last = tick - last, tick
        if kind == "on":
            down.add(a)
            track.append(mido.Message("note_on", note=int(a), velocity=max(1, min(127, int(b))), time=delta))
        elif kind == "off":
            down.discard(a)
            track.append(mido.Message("note_off", note=int(a), velocity=64, time=delta))
        else:
            track.append(mido.Message("control_change", control=int(a), value=max(0, min(127, int(b))), time=delta))
    for p in sorted(down):  # a key that was still down at the stop
        track.append(mido.Message("note_off", note=p, velocity=64, time=0))
    track.append(mido.MetaMessage("end_of_track", time=TICKS))
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


INDEX = "index.json"  # the summaries of the recordings (the list does not read every recording)


def _read_index() -> dict[str, dict] | None:
    try:
        data = json.loads((folder() / INDEX).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        return None
    return data


def _write_index(index: dict[str, dict]) -> None:
    f = folder()
    tmp = f / (INDEX + ".tmp")
    tmp.write_text(json.dumps(index), encoding="utf-8")
    tmp.replace(f / INDEX)


def _index(ids: set[str]) -> dict[str, dict]:
    """The summaries of the recordings with these ids: from the index, and the missing ones from
    their files (an old folder or a lost index). The index is written again when it changed."""
    old = _read_index() or {}
    index = {k: v for k, v in old.items() if k in ids}
    for rec_id in sorted(ids - set(index)):
        try:
            index[rec_id] = summary(json.loads((folder() / f"{rec_id}.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError):
            log.warning("Recording %s cannot be read", rec_id)
    if index != old:
        try:
            _write_index(index)
        except OSError:
            log.warning("Cannot write the recordings index")
    return index


def _ids() -> set[str]:
    return {p.stem for p in folder().glob("rec-*.json") if _ID_RE.match(p.stem)}


def summary(rec: dict) -> dict:
    return {"id": rec["id"], "title": rec["title"], "created": rec["created"], "seconds": rec["seconds"],
            "notes": rec["notes"], "pedal": rec.get("pedal", False)}


class Recorder:
    def __init__(self, sink: Callable[[dict], None], now: Callable[[], float] = clock.now):
        self.sink = sink
        self.now = now
        self.midi = None  # the server sets the MIDI service (keyboard playback)
        self.echo = None  # the echo guard of riyaz/practice.py
        self._lock = threading.RLock()
        self.recording = False
        self.t0 = 0.0
        self.events: list[list] = []
        self.seq = 0
        self.playing: str | None = None  # recording id that plays on the keyboard
        self._stop_play = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_saved: str | None = None

    # ------------------------------------------------------------------ record

    def start(self) -> dict:
        with self._lock:
            if self.playing:
                raise RecorderError("Stop the playback first. Then start the recording.")
            self.recording = True
            self.t0 = self.now()
            self.events = []
            return self._emit_state()

    def on_midi(self, evt: dict) -> None:
        kind = evt.get("type")
        if kind not in ("note_on", "note_off", "cc"):
            return
        with self._lock:
            if not self.recording:
                return
            t = evt.get("t")
            t = self.now() if t is None else t
            rel = round(max(0.0, t - self.t0), 4)
            if kind == "note_on":
                self.events.append([rel, "on", int(evt["pitch"]), int(evt.get("vel", 80))])
            elif kind == "note_off":
                self.events.append([rel, "off", int(evt["pitch"]), 0])
            elif evt.get("control") == config.SUSTAIN_CC:
                self.events.append([rel, "cc", config.SUSTAIN_CC, int(evt.get("value", 0))])
            full = len(self.events) >= MAX_EVENTS or rel >= MAX_SECONDS
        if full:
            self.stop()

    def stop(self) -> dict:
        """Stop the recording and save it. The state has ``saved`` (the new id) or None (no keys)."""
        with self._lock:
            if not self.recording:
                return self._emit_state()
            self.recording = False
            events, self.events = self.events, []
            seconds = round(self.now() - self.t0, 2)
        saved = None
        if any(e[1] == "on" for e in events):
            saved = self._save(events, seconds)
        with self._lock:
            self.last_saved = saved["id"] if saved else None
            return self._emit_state(saved=summary(saved) if saved else None)

    def _save(self, events: list[list], seconds: float) -> dict:
        f = folder()
        f.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now()
        base = "rec-" + now.strftime("%Y%m%d-%H%M%S")
        rec_id, i = base, 1
        while (f / f"{rec_id}.json").exists():
            i += 1
            rec_id = f"{base}-{i}"
        number = len(list(f.glob("rec-*.json"))) + 1
        rec = {"id": rec_id, "title": f"Recording {number}", "created": now.isoformat(timespec="seconds"),
               "seconds": seconds, "notes": sum(1 for e in events if e[1] == "on"),
               "pedal": any(e[1] == "cc" for e in events), "events": events}
        tmp = f / f"{rec_id}.json.tmp"
        tmp.write_text(json.dumps(rec), encoding="utf-8")
        tmp.replace(f / f"{rec_id}.json")
        index = _read_index() or {}
        index[rec_id] = summary(rec)
        try:
            _write_index(index)
        except OSError:
            log.warning("Cannot write the recordings index")
        self._trim()
        return rec

    def _trim(self) -> None:
        files = sorted(folder().glob("rec-*.json"))
        for p in files[:-KEEP_MAX]:
            p.unlink(missing_ok=True)
            p.with_suffix(".mid").unlink(missing_ok=True)
        if len(files) > KEEP_MAX:
            _index(_ids())

    # ------------------------------------------------------------------ the saved recordings

    @staticmethod
    def list() -> list[dict]:
        """The summaries, newest first. Reads only the small index (and a recording that is not
        in it yet), not every recording."""
        if not folder().is_dir():
            return []
        index = _index(_ids())
        return [index[k] for k in sorted(index, reverse=True)]

    @staticmethod
    def get(rec_id: str) -> dict:
        path = _path(rec_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise RecorderError("The app cannot find this recording.")

    @staticmethod
    def delete(rec_id: str) -> bool:
        path = _path(rec_id)
        if not path.is_file():
            return False
        path.unlink()
        _path(rec_id, ".mid").unlink(missing_ok=True)
        index = _read_index()
        if index is not None and index.pop(rec_id, None) is not None:
            try:
                _write_index(index)
            except OSError:
                log.warning("Cannot write the recordings index")
        return True

    @classmethod
    def export(cls, rec_id: str) -> Path:
        """Write <id>.mid next to the recording. Returns its path."""
        rec = cls.get(rec_id)
        out = _path(rec_id, ".mid")
        out.write_bytes(to_midi(rec))
        return out

    # ------------------------------------------------------------------ play on the keyboard speaker

    def play_keyboard(self, rec_id: str) -> dict:
        rec = self.get(rec_id)
        with self._lock:
            if self.recording:
                raise RecorderError("Stop the recording first. Then play it.")
            if self.midi is None:
                raise RecorderError("The app cannot send notes to the keyboard.")
            self._halt_locked()
            self.playing = rec_id
            self._stop_play = threading.Event()
            self._thread = threading.Thread(target=self._play, args=(rec, self._stop_play), daemon=True,
                                            name="riyaz-recorder-play")
            self._thread.start()
            return self._emit_state()

    def _play(self, rec: dict, stop: threading.Event) -> None:
        t0 = self.now()
        down: set[int] = set()
        try:
            for t, kind, a, b in rec["events"]:
                wait = t0 + float(t) - self.now()
                if wait > 0 and stop.wait(wait):
                    break
                if kind in ("on", "off"):
                    msg = self.midi.note_message(int(a), int(b) if kind == "on" else 0)
                    if kind == "on":
                        down.add(int(a))
                        if self.echo is not None:
                            self.echo.sent(msg.note, self.now())
                    else:
                        down.discard(int(a))
                else:
                    msg = mido.Message("control_change", control=int(a), value=int(b),
                                       channel=getattr(self.midi, "channel", None) or 0)
                self.midi.send(msg)
        except Exception:
            log.exception("Recording playback stopped")
        finally:
            try:
                for p in down:
                    self.midi.send(self.midi.note_message(p, 0))
                if any(e[1] == "cc" for e in rec["events"]):
                    self.midi.send(mido.Message("control_change", control=config.SUSTAIN_CC, value=0,
                                                channel=getattr(self.midi, "channel", None) or 0))
            except Exception:
                log.exception("Cannot send notes off")
            with self._lock:
                if self._stop_play is stop:
                    self.playing = None
                    self._emit_state()

    def _halt_locked(self) -> threading.Thread | None:
        self._stop_play.set()
        th = self._thread
        self._thread = None
        return th

    def stop_playback(self) -> dict:
        with self._lock:
            th = self._halt_locked()
        if th is not None:
            th.join(timeout=2)
        with self._lock:
            self.playing = None
            return self._emit_state()

    def close(self) -> None:
        """The app quits: an open recording is saved (stop), the playback stops."""
        try:
            self.stop()
        except Exception:
            log.exception("Cannot save the open recording")
            with self._lock:
                self.recording = False
        self.stop_playback()

    # ------------------------------------------------------------------ state

    def state(self) -> dict:
        with self._lock:
            return self._state(bump=False)

    def _state(self, bump: bool = True, **extra) -> dict:
        if bump:
            self.seq += 1
        return {"type": "recorder", "seq": self.seq, "recording": self.recording,
                "seconds": round(self.now() - self.t0, 1) if self.recording else 0,
                "events": len(self.events), "playing": self.playing, "last_saved": self.last_saved, **extra}

    def _emit_state(self, **extra) -> dict:
        s = self._state(**extra)
        self.sink(s)
        return s
