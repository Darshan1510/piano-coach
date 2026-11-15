"""Audio import (PLAN 11.3): MP3, WAV or M4A -> a first version of the notes -> a song.

1. The user selects a file. M4A (AAC) is changed to WAV with the macOS tool ``afconvert``
   (argument list, no shell). MP3 and WAV go to the worker as they are.
2. The worker process (riyaz/importers/audio_worker.py) finds the notes with basic-pitch and the
   speed with librosa. The app stays responsive; the page polls the job for the progress.
3. The notes become a MIDI file in memory, and the MIDI importer makes the song (hand split,
   fingering, chords, parts), with the timing fixed to small steps (1/16).
4. The simplifier (riyaz/simplify.py) makes the easy version for the user's level. The page
   opens the result in the song editor, because the notes have errors.

The audio packages (basic-pitch, librosa, numpy ...) are optional (uv group ``audio``). The app
starts without them; ``available()`` tells the page. No demucs and no piano transcription model
(DECISIONS.md, Phase 5a).

All error texts are for the user (ASD-STE100, PLAN 7.4 words).
"""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import math
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path

import mido

from .. import config, simplify, songs
from . import midi_import

log = logging.getLogger("riyaz.audio")

TICKS = 480
BPM_LOW, BPM_HIGH = 50.0, 180.0  # the speed from the beat tracker is moved into this range


class AudioImportError(ValueError):
    """The text is for the user."""


NOT_AVAILABLE_TEXT = ("This version of the app cannot import audio files. Import a MIDI file, "
                      "or start the app from the source code with the audio packages.")

ERROR_TEXTS = {
    "too_long": "The recording is too long. The limit is {minutes} minutes. Use a shorter part of the song.",
    "too_short": "The recording is too short. Use a recording of 2 seconds or more.",
    "read": "The app cannot read this audio file. The file is damaged or the format is not correct. "
            "Select a different file.",
    "model": "The app cannot find the notes in this file. Try again. If the problem stays, "
             "start the app again.",
    "no_notes": "The app found no notes in this recording. Use a recording with clear piano or melody sounds.",
    "convert": "The app cannot change this M4A file to WAV. Select an MP3 or WAV file.",
    "timeout": "The app stopped because the file took too long. Use a shorter recording.",
    "cancelled": "You stopped the import.",
    "busy": "Wait for the import to finish.",
}


def available() -> bool:
    """True when the audio packages are in this app (no import: find_spec only)."""
    try:
        return all(importlib.util.find_spec(m) is not None for m in ("basic_pitch", "librosa", "numpy"))
    except (ImportError, ValueError):
        return False


def worker_command(in_path: Path, out_path: Path) -> list[str]:
    """The command for the worker process (argument list, no shell)."""
    args = [str(in_path), str(out_path), str(config.AUDIO_MAX_SECONDS), str(config.AUDIO_MIN_SECONDS)]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--audio-worker", *args]  # main.py runs the worker
    return [sys.executable, "-m", "riyaz.importers.audio_worker", *args]


def worker_env() -> dict[str, str]:
    """The environment of the worker: numba (librosa) keeps its cache in the data folder."""
    cache = config.data_dir() / "cache" / "numba"
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return {**os.environ, "NUMBA_CACHE_DIR": str(cache), "RIYAZ_PARENT_PID": str(os.getpid())}


def check_file(data: bytes, filename: str) -> str:
    """The file extension (".mp3", ".wav", ".m4a"). Raises AudioImportError."""
    ext = os.path.splitext(filename.lower())[1]
    if ext not in config.AUDIO_EXTENSIONS:
        raise AudioImportError("Select an MP3, WAV or M4A file.")
    if not data:
        raise AudioImportError("The file is empty. Select a different file.")
    if len(data) > config.AUDIO_MAX_BYTES:
        mb = config.AUDIO_MAX_BYTES // (1024 * 1024)
        raise AudioImportError(f"The file is too large. The limit is {mb} MB. Select a smaller file.")
    head = data[:12]
    ok = {
        ".wav": head[:4] == b"RIFF" and head[8:12] == b"WAVE",
        ".mp3": head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0),
        ".m4a": head[4:8] == b"ftyp",
    }[ext]
    if not ok:
        raise AudioImportError("The file is not a correct MP3, WAV or M4A file. Select a different file.")
    return ext


def convert_m4a(src: Path, dst: Path) -> None:
    """M4A -> 16-bit WAV with macOS afconvert (argument list, no shell)."""
    tool = config.AFCONVERT if os.path.exists(config.AFCONVERT) else shutil.which("afconvert")
    if not tool:
        raise AudioImportError(ERROR_TEXTS["convert"])
    try:
        subprocess.run([tool, "-f", "WAVE", "-d", "LEI16", str(src), str(dst)], check=True,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
    except (subprocess.SubprocessError, OSError) as exc:
        log.info("afconvert failed: %r", exc)
        raise AudioImportError(ERROR_TEXTS["convert"]) from None


# ------------------------------------------------------------------------- notes -> song


def song_bpm(raw_bpm: float) -> float:
    """The beat tracker can find double or half the speed: move it into 50-180."""
    bpm = float(raw_bpm) if raw_bpm and math.isfinite(raw_bpm) and raw_bpm > 0 else 100.0
    while bpm > BPM_HIGH:
        bpm /= 2
    while bpm < BPM_LOW:
        bpm *= 2
    return round(bpm, 2)


def beat_offset(beats: list[float], first_onset: float, beat_s: float) -> float:
    """The time of click 0: a beat time of the tracker at or before the first note."""
    if beats:
        t0 = beats[0]
        k = math.ceil((t0 - first_onset) / beat_s - 1e-9) if t0 > first_onset else 0
        return t0 - k * beat_s
    return first_onset


def notes_to_midi(notes: list[list[float]], bpm: float, offset_s: float) -> bytes:
    """Note events (seconds) -> a MIDI file (one track) at one speed."""
    beat_s = 60.0 / bpm
    events = []
    for start, end, pitch, vel in notes:
        a = max(0, round((start - offset_s) / beat_s * TICKS))
        b = max(a + 1, round((end - offset_s) / beat_s * TICKS))
        v = max(1, min(127, int(vel)))
        events.append((a, 1, int(pitch), v))
        events.append((b, 0, int(pitch), 0))
    events.sort()
    mid = mido.MidiFile(type=0, ticks_per_beat=TICKS)
    tr = mido.MidiTrack()
    mid.tracks.append(tr)
    tr.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm), time=0))
    tr.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    now = 0
    for tick, on, pitch, vel in events:
        msg = "note_on" if on else "note_off"
        tr.append(mido.Message(msg, note=pitch, velocity=vel if on else 0, time=tick - now))
        now = tick
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def title_from(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return (stem[:1].upper() + stem[1:])[:60] if stem else "My song"


def build_song(result: dict, filename: str, user_level: int, title: str | None = None) -> tuple[dict, bytes]:
    """The worker result -> (song, MIDI bytes). Raises AudioImportError."""
    notes = [n for n in result.get("notes") or [] if 21 <= int(n[2]) <= 108 and n[1] > n[0]]
    if not notes:
        raise AudioImportError(ERROR_TEXTS["no_notes"])
    bpm = song_bpm(result.get("bpm") or 0)
    offset = beat_offset([float(b) for b in result.get("beats") or []], min(n[0] for n in notes), 60.0 / bpm)
    data = notes_to_midi(notes, bpm, offset)
    try:
        parsed = midi_import.parse(data, os.path.splitext(filename)[0] + ".mid")
        song = midi_import.build_song(parsed, quantize=16, title=title or title_from(filename),
                                      user_level=user_level)
    except midi_import.MidiImportError as exc:
        raise AudioImportError(str(exc)) from None
    song["source"] = "audio"
    song["import"]["audio"] = {"file": os.path.basename(filename)[:120], "notes": len(notes),
                               "bpm_found": result.get("bpm"), "seconds": result.get("seconds"),
                               "duration": result.get("duration"), "backend": result.get("backend")}
    return songs.validate(song), data


# ----------------------------------------------------------------------------------- the jobs


class AudioJobs:
    """Audio imports that run in the background (one worker process each, one at a time)."""

    STAGES = {"save": "Save the file", "convert": "Change the file to WAV", "load": "Read the recording",
              "notes": "Find the notes", "speed": "Find the speed", "song": "Make the song",
              "done": "Done"}

    def __init__(self, user_level=lambda: config.USER_LEVEL_DEFAULT) -> None:
        self.user_level = user_level
        self.jobs: OrderedDict[str, dict] = OrderedDict()
        self.procs: dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.run_lock = threading.Lock()  # one transcription at a time (memory)
        # Files of an import that did not finish (the app stopped) go away at the start.
        shutil.rmtree(config.audio_tmp_path(), ignore_errors=True)

    def _set(self, job_id: str, **kw) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is not None:
                job.update(kw)
                job["updated"] = time.time()

    def get(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            return None if job is None else {k: v for k, v in job.items() if not k.startswith("_")}

    def start(self, data: bytes, filename: str, title: str | None = None) -> dict:
        """Check the file, then start the job in a thread. Returns the job. Raises AudioImportError."""
        if not available():
            raise AudioImportError(NOT_AVAILABLE_TEXT)
        ext = check_file(data, filename)
        job_id = secrets.token_hex(8)
        job = {"id": job_id, "state": "running", "stage": "save", "stage_text": self.STAGES["save"],
               "progress": 0.0, "file": os.path.basename(filename)[:120], "error": None, "song": None,
               "easy": None, "started": time.time(), "_cancel": False}
        with self.lock:
            if any(j["state"] == "running" for j in self.jobs.values()):
                raise AudioImportError(ERROR_TEXTS["busy"])  # one import at a time
            self.jobs[job_id] = job
            done = [k for k, j in self.jobs.items() if j["state"] != "running"]
            while len(self.jobs) > config.AUDIO_JOBS_MAX and done:
                self.jobs.pop(done.pop(0), None)
        threading.Thread(target=self._run, args=(job_id, data, filename, ext, title), daemon=True,
                         name="riyaz-audio").start()
        return self.get(job_id)

    def cancel(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            job["_cancel"] = True
            proc = self.procs.get(job_id)
        if proc is not None and proc.poll() is None:
            proc.kill()
        return self.get(job_id)

    def stop_all(self) -> None:
        for job_id in list(self.procs):
            self.cancel(job_id)

    def _cancelled(self, job_id: str) -> bool:
        with self.lock:
            return bool(self.jobs.get(job_id, {}).get("_cancel"))

    def _run(self, job_id: str, data: bytes, filename: str, ext: str, title: str | None) -> None:
        folder = config.audio_tmp_path() / job_id
        try:
            with self.run_lock:
                folder.mkdir(parents=True, exist_ok=True)
                src = folder / f"input{ext}"
                src.write_bytes(data)
                if ext == ".m4a":
                    self._set(job_id, stage="convert", stage_text=self.STAGES["convert"], progress=0.0)
                    wav = folder / "input.wav"
                    convert_m4a(src, wav)
                    src = wav
                if self._cancelled(job_id):
                    raise AudioImportError(ERROR_TEXTS["cancelled"])
                result = self._transcribe(job_id, src, folder / "result.json")
                self._set(job_id, stage="song", stage_text=self.STAGES["song"], progress=0.0)
                level = int(self.user_level())
                song, midi = build_song(result, filename, level, title)
                midi_import.save(song, midi)
                easy = None
                try:
                    easy = simplify.for_level(song, level)  # None: the song fits the level (no version)
                    if easy is not None:
                        simplify.save(easy)
                except (simplify.SimplifyError, songs.SongError) as exc:
                    log.info("No easy version: %s", exc)
                    easy = None
                self._set(job_id, state="done", stage="done", stage_text=self.STAGES["done"], progress=1.0,
                          song=songs.summary(song, level), easy=songs.summary(easy, level) if easy else None,
                          note_count=len(result.get("notes") or []), seconds=result.get("seconds"),
                          duration=result.get("duration"), bpm=song["bpm"])
        except AudioImportError as exc:
            state = "cancelled" if self._cancelled(job_id) else "error"
            self._set(job_id, state=state, error=str(exc) if state == "error" else ERROR_TEXTS["cancelled"])
        except Exception:
            log.exception("Audio import failed")
            self._set(job_id, state="error", error=ERROR_TEXTS["model"])
        finally:
            with self.lock:
                self.procs.pop(job_id, None)
            shutil.rmtree(folder, ignore_errors=True)

    def _transcribe(self, job_id: str, src: Path, out: Path) -> dict:
        cmd = worker_command(src, out)
        self._set(job_id, stage="load", stage_text=self.STAGES["load"], progress=0.0)
        err_path = out.with_suffix(".log")
        with open(err_path, "wb") as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=err,
                                    cwd=str(config.base_path()), text=True, bufsize=1, env=worker_env())
            with self.lock:
                self.procs[job_id] = proc
            if self._cancelled(job_id):
                proc.kill()
            timer = threading.Timer(config.AUDIO_WORKER_TIMEOUT_S, proc.kill)
            timer.daemon = True
            timer.start()
            code = None
            started = time.monotonic()
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    try:
                        msg = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("error"):
                        code = str(msg["error"])
                    elif msg.get("stage") in self.STAGES:
                        self._set(job_id, stage=msg["stage"], stage_text=self.STAGES[msg["stage"]],
                                  progress=float(msg.get("progress") or 0.0))
                proc.wait()
            finally:
                timer.cancel()
        if self._cancelled(job_id):
            raise AudioImportError(ERROR_TEXTS["cancelled"])
        if code:
            text = ERROR_TEXTS.get(code, ERROR_TEXTS["model"])
            raise AudioImportError(text.format(minutes=config.AUDIO_MAX_SECONDS // 60))
        if proc.returncode != 0 or not out.exists():
            if time.monotonic() - started >= config.AUDIO_WORKER_TIMEOUT_S - 1:
                raise AudioImportError(ERROR_TEXTS["timeout"])
            log.warning("Audio worker exit %s: %s", proc.returncode, err_path.read_text(errors="replace")[-2000:])
            raise AudioImportError(ERROR_TEXTS["model"])
        return json.loads(out.read_text(encoding="utf-8"))
