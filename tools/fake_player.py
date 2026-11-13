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
Imported songs (Phase 3a):
  uv run tools/fake_player.py --song my-la-native-f2ad24 --hands RL --follow http://127.0.0.1:8020
      # an imported song id: the tool asks the running app for the song
  uv run tools/fake_player.py --song imported --hands RL --follow http://127.0.0.1:8020
      # every imported song in the running app
  uv run tools/fake_player.py --song "$HOME/Library/Application Support/Riyaz/songs/my-x.json" --hands RL
      # a song JSON file (with --follow, the app must know the song id)
Course and daily session (Phase 3b):
  uv run tools/fake_player.py --autoplay http://127.0.0.1:8020 --until 600
      # follow the app: play what each drill (keyboard basics, skill moment, warm-up, "Find the key")
      # and each wait-mode stop expects. Use it while you click through the app window.
  uv run tools/fake_player.py --session http://127.0.0.1:8020 --minutes 10
      # a whole daily session without the window: start it, do each block (with the skill moments
      # inside the song), end it, print the summary. Exit 1 if something fails.
  uv run tools/fake_player.py --basics http://127.0.0.1:8020
      # do all keyboard basics tasks (and the 10-note demo)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
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


def load_song(name: str, base: str | None = None) -> dict:
    """A song id (data/songs, the user songs folder, or the running app at base) or a JSON file."""
    sys.path.insert(0, str(ROOT))
    from riyaz import songs

    path = Path(name).expanduser()
    if path.suffix == ".json" and path.exists():
        return songs.load_file(path)
    song = songs.get(name)
    if song is None and base:
        try:
            with urllib.request.urlopen(f"{base}/api/songs/{urllib.parse.quote(name)}", timeout=10) as res:
                song = json.loads(res.read())
        except OSError:
            song = None
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


# ---------------------------------------------------------------------- course and daily session (Phase 3b)


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=10) as res:
        return json.loads(res.read())


class AutoPlayer:
    """Plays what the app expects: drill steps (keys, hold, pause, soft/loud, keys together) and
    wait-mode stops. Call handle() with each WebSocket message."""

    def __init__(self, fp: "FakePlayer", delay: float = 0.12, wrong: int = 0):
        self.fp = fp
        self.delay = delay
        self.wrong_left = wrong
        self.last_stop = None
        self.last_drill = None
        self.presses = 0
        self.wrong_pressed = 0
        self._busy = False
        self.drill_seq = None  # the newest drill state: an older planned press is not sent

    def handle(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "practice" and msg.get("waiting") and msg.get("expected"):
            key = (msg.get("song_id"), msg.get("run"), msg.get("stop_index"))
            if key != self.last_stop:
                self.last_stop = key
                asyncio.get_running_loop().create_task(self._press([e["pitch"] for e in msg["expected"]]))
        elif kind == "drill":
            self.drill_seq = msg.get("seq")
        if kind == "drill" and msg.get("status") == "active" and msg.get("expect"):
            k = msg["kind"]
            key = (msg["run"], msg.get("try_index"), msg.get("step"), msg.get("round"), len(msg.get("collected") or []),
                   msg.get("last") in ("wrong_key", "too_short", "too_early", "too_soft", "too_loud") and msg.get("seq"))
            if key == self.last_drill or msg.get("holding"):
                return
            self.last_drill = key
            exp = msg["expect"]
            split = msg.get("vel_split", 64)
            vel = max(1, split - 30) if exp.get("vel") == "soft" else min(127, split + 30) if exp.get("vel") == "loud" else 80
            if exp.get("all"):
                pitches = exp["all"]
            else:
                choices = exp.get("any") or [60]
                pitches = [min(choices, key=lambda p: abs(p - 60))] if k == "find_key" else [choices[0]]
            wrong = None
            if self.wrong_left > 0 and k != "collect":
                self.wrong_left -= 1
                wrong = next(p for p in range(max(pitches) + 1, 97) if p not in pitches and p % 12 != pitches[0] % 12)
            asyncio.get_running_loop().create_task(
                self._press(pitches, vel=vel, hold=float(exp.get("hold") or 0), rest=float(exp.get("rest") or 0), wrong=wrong,
                            seq=msg.get("seq")))

    async def _press(self, pitches, vel=80, hold=0.0, rest=0.0, wrong=None, seq=None):
        while self._busy:
            await asyncio.sleep(0.01)
        self._busy = True
        try:
            await asyncio.sleep(self.delay + rest)
            if seq is not None and seq != self.drill_seq:
                return  # the drill moved on: a newer state plans its own press
            if wrong is not None:
                self.fp.note_on(wrong, 80)
                await asyncio.sleep(0.03)
                self.fp.note_off(wrong)
                self.wrong_pressed += 1
                return  # the drill sends a new state (a try starts again): it plans the right press
            for p in pitches:
                self.fp.note_on(p, vel)
            self.presses += 1
            await asyncio.sleep(max(0.03, hold + 0.1 if hold else 0.03))
            for p in pitches:
                self.fp.note_off(p)
        finally:
            self._busy = False


class AppLink:
    """One WebSocket to the app: the autoplayer sees each message; wait_for() waits for one."""

    def __init__(self, base: str, player: AutoPlayer):
        self.base = base
        self.player = player
        self.waiters: list = []
        self.log: list[dict] = []

    async def __aenter__(self):
        import websockets

        self.ws = await websockets.connect(self.base.replace("http://", "ws://") + "/ws")
        self.task = asyncio.create_task(self._read())
        return self

    async def __aexit__(self, *exc):
        self.task.cancel()
        await self.ws.close()

    async def _read(self):
        async for text in self.ws:
            msg = json.loads(text)
            if msg.get("type") in ("drill", "practice_skill", "practice_end", "course", "drill_wrong"):
                self.log.append(msg)
            self.player.handle(msg)
            for w in list(self.waiters):
                pred, fut = w
                if not fut.done() and pred(msg):
                    fut.set_result(msg)
                    self.waiters.remove(w)

    def expect(self, pred):
        fut = asyncio.get_running_loop().create_future()
        self.waiters.append((pred, fut))
        return fut

    async def wait(self, fut, timeout: float = 300.0):
        return await asyncio.wait_for(fut, timeout)


async def do_drill(link: AppLink, body: dict) -> dict:
    fut = link.expect(lambda m: m.get("type") == "drill" and m.get("status") == "passed")
    st = _post(link.base, "/api/drill/start", body)
    msg = await link.wait(fut)
    assert msg["run"] == st["run"], (msg, st)
    return msg


async def play_practice(link: AppLink, song_id: str, hands, section=None, speed: float = 1.0) -> dict:
    """Wait mode with the skill moments (PLAN 8.2), as the app window does it."""
    song = _get(link.base, f"/api/songs/{song_id}")
    sec = song["sections"][section] if section is not None else None
    rs, re_ = (sec["start"], sec["end"]) if sec else (0.0, song["end"])
    moments = [m for m in _get(link.base, f"/api/course/moments/{song_id}")["moments"]
               if set(m["hands"]) <= set(hands) and rs - 1e-6 <= m["at_beat"] < re_ - 1e-6]
    skills = []
    for m in [m for m in moments if m["at_beat"] <= rs + 1e-6]:  # at the start: before the song
        r = await do_drill(link, {"source": "skill", "ref": m["id"]})
        skills.append((m["id"], r["result"].get("unlocked")))
    later = [m for m in moments if m["at_beat"] > rs + 1e-6]
    st = _post(link.base, "/api/practice/start", {
        "song_id": song_id, "mode": "wait", "hands": list(hands), "speed": speed, "section": section,
        "count_in": False, "accompany": True, "loop": False, "breaks": [{"beat": m["at_beat"], "skill": m["id"]} for m in later]})
    run = st["run"]
    course_fut = link.expect(lambda m: m.get("type") == "course" and m.get("run") == run and m.get("song_id") == song_id)
    while True:
        msg = await link.wait(link.expect(lambda m: m.get("run") == run and m.get("type") in ("practice_skill", "practice_end")
                                          and m.get("song_id") == song_id))
        if msg["type"] == "practice_end":
            course = await link.wait(course_fut, 10)
            return {"end": msg, "course": course, "skills": skills}
        m = next(x for x in later if x["id"] == msg["skill"])
        r = await do_drill(link, {"source": "skill", "ref": m["id"]})
        skills.append((m["id"], r["result"].get("unlocked")))
        _post(link.base, "/api/practice/seek", {"beat": m["resume_beat"], "run": run})


async def run_session(base: str, fp: "FakePlayer", minutes: int = 10, wrong: int = 0) -> dict:
    player = AutoPlayer(fp, wrong=wrong)
    t0 = time.perf_counter()
    async with AppLink(base, player) as link:
        s = _post(base, "/api/session/start", {"minutes": minutes})
        sid = s["id"]
        report = {"session": sid, "minutes": s["plan"]["minutes"], "blocks": []}
        for i, b in enumerate(s["plan"]["blocks"]):
            bt = time.perf_counter()
            info = {"kind": b["kind"]}
            if b["kind"] in ("warmup", "intuition"):
                r = await do_drill(link, {"source": "session", "session_id": sid, "block": i})
                info.update(drill=r["id"], wrong=r["wrong"], times=r.get("times"))
            elif b["kind"] == "song":
                runs = []
                for step in b["steps"]:
                    r = await play_practice(link, b["song_id"], b["hands"], step["section"], step["speed"] or 1.0)
                    runs.append({"section": step["section"], "accuracy": r["end"].get("accuracy"),
                                 "done": r["course"]["done"], "skills": r["skills"]})
                info.update(song=b["song_id"], runs=runs)
            else:
                r = await play_practice(link, b["song_id"], b["hands"], b["section"], 1.0)
                info.update(song=b["song_id"], section=b["section"], accuracy=r["end"].get("accuracy"))
            _post(base, f"/api/session/{sid}/block", {"index": i, "status": "done",
                                                      "seconds": time.perf_counter() - bt})
            info["seconds"] = round(time.perf_counter() - bt, 1)
            report["blocks"].append(info)
        end = _post(base, f"/api/session/{sid}/end", {})
        report["summary"] = end["summary"]
        report["seconds"] = round(time.perf_counter() - t0, 1)
        report["wrong_pressed"] = player.wrong_pressed
    return report


async def run_basics(base: str, fp: "FakePlayer") -> dict:
    player = AutoPlayer(fp)
    out = []
    async with AppLink(base, player) as link:
        course = _get(base, "/api/course")
        for step in course["basics"]["steps"]:
            for task in step["tasks"]:
                if "drill" in task:
                    r = await do_drill(link, {"source": "basics", "ref": task["id"]})
                    out.append((task["id"], r["result"].get("unlocked")))
                else:
                    r = await play_practice(link, task["practice"], ["R"], None, 1.0)
                    out.append((task["id"], r["course"].get("unlocked")))
    return {"tasks": out, "basics_done": _get(base, "/api/course")["basics"]["done"]}


async def autoplay(base: str, fp: "FakePlayer", until: float, wrong: int = 0) -> dict:
    player = AutoPlayer(fp, wrong=wrong)
    async with AppLink(base, player):
        await asyncio.sleep(until)
    return {"presses": player.presses, "wrong_pressed": player.wrong_pressed}


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
    ap.add_argument("--autoplay", metavar="URL", help="follow the app: play each drill and wait-mode stop")
    ap.add_argument("--until", type=float, default=600, help="with --autoplay: seconds to run")
    ap.add_argument("--session", metavar="URL", help="run a whole daily session in the app at URL")
    ap.add_argument("--minutes", type=int, default=10, help="with --session: 10, 15, 20 or 30")
    ap.add_argument("--basics", metavar="URL", help="do the keyboard basics in the app at URL")
    args = ap.parse_args()

    if args.autoplay or args.session or args.basics:
        base = args.autoplay or args.session or args.basics
        sys.path.insert(0, str(ROOT))
        from tools.measure_latency import wait_connected

        with FakePlayer(args.name, shift=args.shift, channel=args.channel - 1, vel0_note_off=not args.note_off) as fp:
            print(f"Virtual port '{args.name}' is open.", flush=True)
            wait_connected(base, args.name)
            if args.autoplay:
                r = asyncio.run(autoplay(base, fp, args.until, args.wrong))
            elif args.basics:
                r = asyncio.run(run_basics(base, fp))
            else:
                r = asyncio.run(run_session(base, fp, args.minutes, args.wrong))
            print(json.dumps(r, indent=1), flush=True)
            time.sleep(args.hold)
        if args.basics and not r["basics_done"]:
            raise SystemExit(1)
        return

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
        if args.song == "all":
            ids = [s["id"] for s in songs.list_summaries() if not s["id"].startswith("test-") and s["source"] == "builtin"]
        elif args.song == "imported":
            with urllib.request.urlopen(f"{args.follow}/api/songs", timeout=10) as res:
                ids = [s["id"] for s in json.loads(res.read())["songs"] if s.get("source") == "midi"]
        else:
            ids = [load_song(args.song, args.follow)["id"]]
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
