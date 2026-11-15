"""Audio transcription worker (PLAN 11.3). Runs in its own process, so that the app stays
responsive and the memory goes back to the system after each file.

  python -m riyaz.importers.audio_worker IN.wav OUT.json      (source run)
  Riyaz --audio-worker IN.wav OUT.json                        (frozen app, see main.py)

Steps: read the audio (mono, 22050 Hz, librosa), basic-pitch (Spotify, Apache-2.0) with its
CoreML model -> notes, librosa.beat.beat_track -> speed and click times.

Protocol: one JSON object per line on stdout:
  {"stage": "load" | "notes" | "speed" | "done", "progress": 0..1}
  {"error": "code", "seconds": n}                  (codes: too_long, too_short, read, model)
Everything that the libraries print goes to stderr. The result goes to OUT.json:
  {"notes": [[start_s, end_s, pitch, velocity]], "bpm": n, "beats": [s], "duration": s,
   "seconds": n, "backend": "COREML"}

basic-pitch is used through one function (transcribe()), so that it can be replaced later
(RESEARCH.md risk 7).
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings


def _protocol():
    """A file for the protocol (the real stdout). Library prints go to stderr from now on."""
    fd = os.dup(1)
    os.dup2(2, 1)
    return os.fdopen(fd, "w", buffering=1)


def watch_parent(interval: float = 1.0) -> None:
    """The worker stops when the app process stops (the parent process changes)."""
    import threading

    try:  # the app gives its process id (the worker can start after a fast parent stop)
        parent = int(os.environ.get("RIYAZ_PARENT_PID") or os.getppid())
    except ValueError:
        parent = os.getppid()

    def loop():
        while True:
            time.sleep(interval)
            if os.getppid() != parent:
                os._exit(4)

    threading.Thread(target=loop, daemon=True, name="riyaz-parent-watch").start()


def transcribe(y, report) -> tuple[list[list[float]], str]:
    """Notes from mono audio at 22050 Hz with basic-pitch. report(progress 0..1)."""
    import numpy as np
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.constants import AUDIO_N_SAMPLES, FFT_HOP, AUDIO_SAMPLE_RATE
    from basic_pitch.inference import Model, unwrap_output, window_audio_file
    from basic_pitch import note_creation as infer

    model = Model(ICASSP_2022_MODEL_PATH)
    n_overlap = 30
    overlap_len = n_overlap * FFT_HOP
    hop = AUDIO_N_SAMPLES - overlap_len
    original_length = y.shape[0]
    audio = np.concatenate([np.zeros((overlap_len // 2,), dtype=np.float32), y.astype(np.float32)])
    windows = max(1, int(np.ceil(audio.shape[0] / hop)))
    out: dict[str, list] = {"note": [], "onset": [], "contour": []}
    for i, (window, _t) in enumerate(window_audio_file(audio, hop)):
        for k, v in model.predict(np.expand_dims(window, axis=0)).items():
            out[k].append(v)
        report(min(1.0, (i + 1) / windows))
    unwrapped = {k: unwrap_output(np.concatenate(out[k]), original_length, n_overlap) for k in out}
    min_len = int(np.round(127.70 / 1000 * (AUDIO_SAMPLE_RATE / FFT_HOP)))
    _midi, events = infer.model_output_to_notes(unwrapped, onset_thresh=0.5, frame_thresh=0.3,
                                                min_note_len=min_len, min_freq=None, max_freq=None,
                                                multiple_pitch_bends=False, melodia_trick=True)
    notes = [[float(s), float(e), int(p), int(round(127 * float(a)))] for s, e, p, a, _b in events]
    notes.sort()
    return notes, model.model_type.name


def run(in_path: str, out_path: str, max_seconds: float, min_seconds: float, proto) -> int:
    def say(**obj):
        proto.write(json.dumps(obj) + "\n")
        proto.flush()

    t0 = time.monotonic()
    say(stage="load", progress=0.0)
    warnings.filterwarnings("ignore")
    try:
        import librosa
        import numpy as np
    except Exception as exc:  # the audio packages are not there
        print(f"import error: {exc!r}", file=sys.stderr)
        say(error="model")
        return 3
    try:
        duration = float(librosa.get_duration(path=in_path))
    except Exception as exc:
        print(f"read error: {exc!r}", file=sys.stderr)
        say(error="read")
        return 2
    if duration > max_seconds:
        say(error="too_long", seconds=round(duration, 1))
        return 2
    if duration < min_seconds:
        say(error="too_short", seconds=round(duration, 1))
        return 2
    try:
        y, sr = librosa.load(in_path, sr=22050, mono=True)
    except Exception as exc:
        print(f"read error: {exc!r}", file=sys.stderr)
        say(error="read")
        return 2
    say(stage="notes", progress=0.0)
    try:
        notes, backend = transcribe(y, lambda p: say(stage="notes", progress=round(p, 3)))
    except Exception as exc:
        print(f"model error: {exc!r}", file=sys.stderr)
        say(error="model")
        return 3
    say(stage="speed", progress=0.0)
    try:
        tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(np.atleast_1d(tempo)[0])
        beats = [round(float(t), 4) for t in librosa.frames_to_time(frames, sr=sr)]
    except Exception as exc:
        print(f"beat error: {exc!r}", file=sys.stderr)
        bpm, beats = 0.0, []
    result = {"notes": notes, "bpm": round(bpm, 3), "beats": beats, "duration": round(duration, 3),
              "seconds": round(time.monotonic() - t0, 2), "backend": backend}
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f)
    os.replace(tmp, out_path)
    say(stage="done", progress=1.0)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--audio-worker":
        argv = argv[1:]
    if len(argv) < 2:
        print("usage: audio_worker IN OUT [MAX_SECONDS MIN_SECONDS]", file=sys.stderr)
        return 1
    max_s = float(argv[2]) if len(argv) > 2 else 360.0
    min_s = float(argv[3]) if len(argv) > 3 else 2.0
    watch_parent()
    proto = _protocol()
    return run(argv[0], argv[1], max_s, min_s, proto)


if __name__ == "__main__":
    sys.exit(main())
