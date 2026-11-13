"""Fake keyboard: a virtual MIDI port that plays notes into Riyaz.

The app sees the port "Riyaz Fake Keyboard" as a MIDI input, like the USB-MIDI cable.

Examples:
  uv run tools/fake_player.py                      # play a short tune (Twinkle), then exit
  uv run tools/fake_player.py --shift 12           # as if OCTAVE/TRANSPOSE were +12
  uv run tools/fake_player.py --notes 60,64,67 --chord   # press C-E-G together
  uv run tools/fake_player.py --wait 3 --repeat 0  # wait 3 s for the app, then loop forever
  uv run tools/fake_player.py --noise              # also send clock/start/stop/program change

Songs (Phase 2):
  uv run tools/fake_player.py --song ode-to-joy                 # play the right hand of a song, in time
  uv run tools/fake_player.py --song ode-to-joy --follow http://127.0.0.1:8020
      # start wait mode in the running app, press each expected key when the song waits, until the end
  uv run tools/fake_player.py --song all --follow http://127.0.0.1:8020 --wrong 2 --speed 1.5
      # every built-in song; also press 2 wrong keys in each song (they must not advance the song)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

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


# ---------------------------------------------------------------------- songs (Phase 2)

ROOT = Path(__file__).resolve().parent.parent


def load_song(name: str) -> dict:
    """A song id (data/songs) or a path to a song JSON file."""
    sys.path.insert(0, str(ROOT))
    from riyaz import songs

    path = Path(name)
    if path.suffix == ".json" and path.exists():
        return songs.load_file(path)
    song = songs.get(name)
    if song is None:
        raise SystemExit(f"Song not found: {name}")
    return song


def song_notes(song: dict, hands=("R",)) -> list[dict]:
    return sorted((n for n in song["notes"] if n["hand"] in hands), key=lambda n: (n["start"], n["pitch"]))


def play_song(fp: "FakePlayer", song: dict, hands=("R",), speed: float = 1.0) -> None:
    """Play the notes of the song in time (as a player who knows the song)."""
    beat_s = 60.0 / (song["bpm"] * speed)
    events = []
    for n in song_notes(song, hands):
        events.append((n["start"] * beat_s, 1, n["pitch"], n["vel"]))
        events.append(((n["start"] + n["dur"] * 0.9) * beat_s, 0, n["pitch"], 0))
    events.sort(key=lambda e: (e[0], e[1]))  # note off before note on at the same time
    t0 = time.perf_counter()
    for at, on, pitch, vel in events:
        delay = t0 + at - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        fp.note_on(pitch, vel) if on else fp.note_off(pitch)


def _post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


async def follow_wait(base: str, fp: "FakePlayer", song_id: str, hands=("R",), speed: float = 1.5,
                      wrong: int = 0, count_in: bool = False, timeout: float = 300.0) -> dict:
    """Wait mode with the running app: press the expected keys each time the song waits.

    With wrong > 0, first press a wrong key at the first `wrong` stops; the song must not go on.
    Returns a summary: stops, wrong events, wrong events that advanced the song (must be 0), end event.
    """
    import websockets

    ws_url = base.replace("http://", "ws://") + "/ws"
    async with websockets.connect(ws_url) as ws:
        _post(base, "/api/practice/start", {"song_id": song_id, "mode": "wait", "hands": list(hands),
                                            "speed": speed, "count_in": count_in, "accompany": False})
        handled: set[int] = set()
        wrong_left = wrong
        wrong_events: list[dict] = []
        advanced_on_wrong = 0
        hits = 0
        t0 = time.perf_counter()
        end = None
        while end is None:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            kind = msg.get("type")
            if kind == "practice" and msg.get("song_id") == song_id:
                idx = msg.get("stop_index")
                if msg.get("waiting") and idx not in handled:
                    handled.add(idx)
                    expected = [e["pitch"] for e in msg["expected"]]
                    if wrong_left > 0:
                        wrong_left -= 1
                        bad = next(p for p in range(max(expected) + 1, 97) if p not in expected)
                        fp.tap(bad, 0.03)
                        await asyncio.sleep(0.15)
                        # The song must still wait at the same stop after the wrong key.
                        state = json.loads(urllib.request.urlopen(base + "/api/practice", timeout=5).read())
                        if state["stop_index"] != idx or not state["waiting"]:
                            advanced_on_wrong += 1
                    for p in expected:
                        fp.note_on(p)
                    await asyncio.sleep(0.03)
                    for p in expected:
                        fp.note_off(p)
            elif kind == "practice_wrong":
                wrong_events.append({"pitch": msg["pitch"], "stop": msg["stop"]})
            elif kind == "practice_hit":
                hits += 1
            elif kind == "practice_end" and msg.get("song_id") == song_id:
                end = msg
    return {"song": song_id, "stops": end["stops"], "wrong_reported": end["wrong"],
            "wrong_events": len(wrong_events), "advanced_on_wrong": advanced_on_wrong, "hits": hits,
            "completed": end["completed"], "seconds": round(time.perf_counter() - t0, 2)}


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
    ap.add_argument("--song", help="song id or JSON file ('all' with --follow: every built-in song)")
    ap.add_argument("--hands", default="R", help="R, L or RL (song notes to play)")
    ap.add_argument("--speed", type=float, default=1.0, help="song speed (wait mode default 1.5)")
    ap.add_argument("--follow", metavar="URL", help="start wait mode in the app at URL and follow it")
    ap.add_argument("--wrong", type=int, default=0, help="with --follow: wrong keys to press first")
    args = ap.parse_args()

    if args.song:
        play_songs(args)
        return

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


def play_songs(args) -> None:
    hands = tuple(args.hands)
    with FakePlayer(args.name, shift=args.shift, channel=args.channel - 1, vel0_note_off=not args.note_off) as fp:
        print(f"Virtual port '{args.name}' is open.")
        if not args.follow:
            time.sleep(args.wait)
            play_song(fp, load_song(args.song), hands, args.speed)
            time.sleep(args.hold)
            return
        sys.path.insert(0, str(ROOT))
        from riyaz import songs
        from tools.measure_latency import wait_connected

        wait_connected(args.follow, args.name)
        ids = [s["id"] for s in songs.list_summaries() if not s["id"].startswith("test-")] \
            if args.song == "all" else [load_song(args.song)["id"]]
        speed = args.speed if args.speed != 1.0 else 1.5
        failed = 0
        for sid in ids:
            r = asyncio.run(follow_wait(args.follow, fp, sid, hands, speed, args.wrong))
            ok = r["completed"] and r["advanced_on_wrong"] == 0 and r["wrong_events"] == args.wrong
            failed += not ok
            print(("PASS " if ok else "FAIL ") + json.dumps(r))
        if failed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
