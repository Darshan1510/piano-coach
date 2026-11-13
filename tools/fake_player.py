"""Fake keyboard: a virtual MIDI port that plays notes into Riyaz.

The app sees the port "Riyaz Fake Keyboard" as a MIDI input, like the USB-MIDI cable.

Examples:
  uv run tools/fake_player.py                      # play a short tune (Twinkle), then exit
  uv run tools/fake_player.py --shift 12           # as if OCTAVE/TRANSPOSE were +12
  uv run tools/fake_player.py --notes 60,64,67 --chord   # press C-E-G together
  uv run tools/fake_player.py --wait 3 --repeat 0  # wait 3 s for the app, then loop forever
  uv run tools/fake_player.py --noise              # also send clock/start/stop/program change
"""

from __future__ import annotations

import argparse
import time

import mido

PORT_NAME = "Riyaz Fake Keyboard"

# Twinkle Twinkle Little Star, first line (traditional, public domain). (pitch, beats)
TWINKLE = [(60, 1), (60, 1), (67, 1), (67, 1), (69, 1), (69, 1), (67, 2),
           (65, 1), (65, 1), (64, 1), (64, 1), (62, 1), (62, 1), (60, 2)]


class FakePlayer:
    """A virtual output port. Use it from tests or from the command line."""

    def __init__(self, name: str = PORT_NAME, shift: int = 0, channel: int = 0, vel0_note_off: bool = True):
        self.name = name
        self.shift = shift
        self.channel = channel
        self.vel0_note_off = vel0_note_off  # the YPT-320 sends note_on velocity 0 for note off
        self.port = mido.open_output(name, virtual=True)

    def close(self) -> None:
        self.port.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def note_on(self, pitch: int, velocity: int = 80) -> float:
        """Press a key. Returns time.perf_counter() just before the send."""
        t = time.perf_counter()
        self.port.send(mido.Message("note_on", note=pitch + self.shift, velocity=velocity, channel=self.channel))
        return t

    def note_off(self, pitch: int) -> float:
        t = time.perf_counter()
        if self.vel0_note_off:
            msg = mido.Message("note_on", note=pitch + self.shift, velocity=0, channel=self.channel)
        else:
            msg = mido.Message("note_off", note=pitch + self.shift, velocity=64, channel=self.channel)
        self.port.send(msg)
        return t

    def sustain(self, down: bool) -> None:
        self.port.send(mido.Message("control_change", control=64, value=127 if down else 0, channel=self.channel))

    def noise(self) -> None:
        """Messages that the YPT-320 can send in PC mode OFF. The app must ignore them."""
        for msg in (mido.Message("clock"), mido.Message("start"), mido.Message("stop"),
                    mido.Message("program_change", program=5, channel=self.channel),
                    mido.Message("sysex", data=[0x43, 0x10, 0x4C]),
                    mido.Message("note_on", note=48, velocity=70, channel=(self.channel + 9) % 16),
                    mido.Message("note_on", note=48, velocity=0, channel=(self.channel + 9) % 16)):
            self.port.send(msg)

    def tap(self, pitch: int, seconds: float = 0.2, velocity: int = 80) -> None:
        self.note_on(pitch, velocity)
        time.sleep(seconds)
        self.note_off(pitch)

    def play(self, notes: list[tuple[int, float]], bpm: float = 100, velocity: int = 80, noise: bool = False) -> None:
        beat = 60.0 / bpm
        for pitch, beats in notes:
            if noise:
                self.noise()
            self.note_on(pitch, velocity)
            time.sleep(beats * beat * 0.9)
            self.note_off(pitch)
            time.sleep(beats * beat * 0.1)

    def chord(self, pitches: list[int], seconds: float = 1.0, velocity: int = 80) -> None:
        for p in pitches:
            self.note_on(p, velocity)
        time.sleep(seconds)
        for p in pitches:
            self.note_off(p)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=PORT_NAME, help="virtual port name")
    ap.add_argument("--shift", type=int, default=0, help="add this many semitones to each note (for example 12)")
    ap.add_argument("--channel", type=int, default=1, help="MIDI channel 1-16")
    ap.add_argument("--notes", help="comma-separated MIDI pitches (default: Twinkle)")
    ap.add_argument("--chord", action="store_true", help="press --notes together")
    ap.add_argument("--bpm", type=float, default=100)
    ap.add_argument("--velocity", type=int, default=80)
    ap.add_argument("--wait", type=float, default=2.5, help="seconds to wait first (the app checks ports every 2 s)")
    ap.add_argument("--repeat", type=int, default=1, help="times to play; 0 = forever")
    ap.add_argument("--noise", action="store_true", help="also send clock, start/stop, sysex, other channel")
    ap.add_argument("--note-off", action="store_true", help="send real note_off (default: note_on velocity 0)")
    ap.add_argument("--hold", type=float, default=0.5, help="seconds to keep the port open at the end")
    args = ap.parse_args()

    with FakePlayer(args.name, shift=args.shift, channel=args.channel - 1, vel0_note_off=not args.note_off) as fp:
        print(f"Virtual port '{args.name}' is open (shift {args.shift:+d}, channel {args.channel}).")
        time.sleep(args.wait)
        count = 0
        while args.repeat == 0 or count < args.repeat:
            if args.notes:
                pitches = [int(x) for x in args.notes.split(",") if x.strip()]
                if args.chord:
                    fp.chord(pitches, 60.0 / args.bpm * 2, args.velocity)
                else:
                    fp.play([(p, 1) for p in pitches], args.bpm, args.velocity, args.noise)
            else:
                fp.play(TWINKLE, args.bpm, args.velocity, args.noise)
            count += 1
        time.sleep(args.hold)


if __name__ == "__main__":
    main()
