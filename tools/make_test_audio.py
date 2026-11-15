"""Make a short test WAV file from a song (a simple additive synth, numpy only).

The audio-import tests use it: the notes of the file are known, so the test can count how many
notes the transcription finds (note accuracy).

  uv run tools/make_test_audio.py ode-to-joy OUT.wav            # built-in song id
  uv run tools/make_test_audio.py data/songs/ode-to-joy.json OUT.wav --hands RL --bpm 100

The sound: 6 harmonics with a fast attack and an exponential decay (like a soft piano).
16-bit mono, 22050 Hz.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RATE = 22050
HARMONICS = (1.0, 0.5, 0.3, 0.18, 0.1, 0.06)


def load_song(name: str) -> dict:
    p = Path(name)
    if p.suffix == ".json" and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    from riyaz import songs

    song = songs.get(name)
    if song is None:
        raise SystemExit(f"No song {name!r}")
    return song


def note_wave(pitch: int, seconds: float, vel: int, rate: int = RATE) -> np.ndarray:
    freq = 440.0 * 2 ** ((pitch - 69) / 12)
    tail = 0.25  # release after the key goes up
    n = int((seconds + tail) * rate)
    t = np.arange(n) / rate
    sig = np.zeros(n)
    for k, amp in enumerate(HARMONICS, start=1):
        if freq * k < rate / 2:
            sig += amp * np.sin(2 * np.pi * freq * k * t) * np.exp(-t * (1.5 + 0.8 * k))
    env = np.minimum(1.0, t / 0.005)  # 5 ms attack
    rel = np.clip((seconds + tail - t) / tail, 0.0, 1.0)  # fade out after the note
    return sig * env * np.where(t > seconds, rel, 1.0) * (vel / 127.0)


def render(notes: list[dict], bpm: float, rate: int = RATE, lead_s: float = 0.5) -> np.ndarray:
    """Notes (start, dur in beats) -> mono float audio. lead_s of quiet before the first note."""
    beat_s = 60.0 / bpm
    end = max(n["start"] + n["dur"] for n in notes) * beat_s + lead_s + 1.0
    out = np.zeros(int(end * rate))
    for n in notes:
        w = note_wave(n["pitch"], n["dur"] * beat_s * 0.95, n.get("vel", 80), rate)
        a = int((lead_s + n["start"] * beat_s) * rate)
        b = min(len(out), a + len(w))
        out[a:b] += w[: b - a]
    peak = np.max(np.abs(out)) or 1.0
    return out / peak * 0.8


def write_wav(path: Path, audio: np.ndarray, rate: int = RATE) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def make(song: dict, path: Path, hands: str = "R", bpm: float | None = None, lead_s: float = 0.5) -> list[dict]:
    """Write the WAV. Returns the notes in seconds: [{"pitch", "onset", "offset"}]."""
    bpm = float(bpm or song["bpm"])
    notes = [n for n in song["notes"] if n["hand"] in hands]
    write_wav(path, render(notes, bpm, lead_s=lead_s))
    beat_s = 60.0 / bpm
    return [{"pitch": n["pitch"], "onset": lead_s + n["start"] * beat_s,
             "offset": lead_s + (n["start"] + n["dur"]) * beat_s} for n in notes]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song")
    ap.add_argument("out")
    ap.add_argument("--hands", default="R", help="R, L or RL")
    ap.add_argument("--bpm", type=float)
    args = ap.parse_args()
    notes = make(load_song(args.song), Path(args.out), args.hands, args.bpm)
    print(f"{args.out}: {len(notes)} notes")


if __name__ == "__main__":
    main()
