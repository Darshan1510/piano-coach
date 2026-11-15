"""FastAPI app: static UI, REST calls for setup, and the WebSocket that carries MIDI events."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import statistics
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse

from . import clock, config, course as course_mod, editor as editor_mod, feedback, review, session as session_mod, \
    simplify, skills as skills_mod, songs
from .course import Course, CourseError
from .db import Store
from .drill import Drill, DrillError
from . import intuition as intuition_mod
from .intuition import Intuition, IntuitionError
from .importers import audio_import, midi_import
from .midi_io import MidiService
from .practice import Practice, PracticeError, clamp_speed
from .session import Activity, Reminder, SessionError, Sessions
from .tapcheck import TapCheck
from . import tapcheck as tapcheck_mod

log = logging.getLogger("riyaz.server")

QUEUE_MAX = 512  # events for one WebSocket client; when full, the oldest event is dropped
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def origin_ok(headers, allowed_hosts: tuple[str, ...] = config.ALLOWED_HOSTS) -> bool:
    """Same-origin check. No Origin header (Python tools, tests) is OK.

    A web page in the browser always sends Origin with a WebSocket and a POST. Only the app's
    own page (http://127.0.0.1:<port> or http://localhost:<port>) may talk to the app.
    """
    origin = headers.get("origin")
    if origin is None:
        return True
    host = headers.get("host", "")
    port = host.rpartition(":")[2] if ":" in host else ""
    own = {f"http://{h}:{port}" if port else f"http://{h}" for h in allowed_hosts}
    return origin in own


class OriginCheckMiddleware:
    """Rejects (403) POST, PUT, PATCH and DELETE requests from another web page (CSRF)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
            if not origin_ok(headers):
                log.warning("Request from another origin blocked: %s", headers.get("origin"))
                await PlainTextResponse("Forbidden origin", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


class Hub:
    """Sends events to all WebSocket clients. publish() is safe to call from any thread."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queues: set[asyncio.Queue[str]] = set()

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def publish(self, evt: dict[str, Any]) -> None:
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        text = json.dumps(evt)
        try:
            loop.call_soon_threadsafe(self._fanout, text)
        except RuntimeError:  # loop closed during shutdown
            pass

    def _fanout(self, text: str) -> None:
        for q in self.queues:
            put_drop_oldest(q, text)


def put_drop_oldest(q: asyncio.Queue, item: str) -> None:
    """A slow or stuck client must not make the queue grow without limit."""
    while True:
        try:
            q.put_nowait(item)
            return
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass


class LatencyLog:
    """Delay reports from the UI (receive time and paint time, in ms)."""

    def __init__(self) -> None:
        self.recv: list[float] = []
        self.paint: list[float] = []

    def add(self, report: dict) -> None:
        # Convert both lists first, so that a bad report adds nothing (ValueError/TypeError).
        recv = [float(x) for x in report.get("recv_ms", [])]
        paint = [float(x) for x in report.get("paint_ms", [])]
        self.recv.extend(recv)
        self.paint.extend(paint)

    @staticmethod
    def _summary(values: list[float]) -> dict:
        if not values:
            return {"n": 0}
        v = sorted(values)
        p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
        return {"n": len(v), "median_ms": round(statistics.median(v), 2), "p95_ms": round(p95, 2),
                "max_ms": round(v[-1], 2)}

    def summary(self) -> dict:
        return {"recv": self._summary(self.recv), "paint": self._summary(self.paint)}


def create_app(start_midi: bool = True, poll_interval: float = config.HOTPLUG_INTERVAL_S) -> FastAPI:
    hub = Hub()
    latency = LatencyLog()
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.attach(asyncio.get_running_loop())
        store = Store()
        course = Course(store)
        activity = Activity(store)
        sessions = Sessions(store, course, activity)
        reminder = Reminder(store, activity)
        state.update(store=store, course=course, activity=activity, sessions=sessions)

        # The result of a run (database writes, the course) is saved on its own thread: the practice
        # sink runs with the practice lock held (practice thread or MIDI thread), and the MIDI
        # thread must not wait for the disk. One worker keeps the runs in order.
        results = ThreadPoolExecutor(max_workers=1, thread_name_prefix="riyaz-results")

        def flush_results(timeout: float = 5.0) -> None:
            """Wait until the saved runs are done (tests and tools)."""
            results.submit(lambda: None).result(timeout=timeout)

        state.update(flush_results=flush_results)

        def practice_sink(evt: dict) -> None:
            hub.publish(evt)
            if evt.get("type") == "practice_end":
                results.submit(on_practice_end, evt)
            elif evt.get("type") == "practice_pass":
                results.submit(on_practice_pass, evt)

        practice = Practice(practice_sink)
        practice.input_offset_s = tapcheck_mod.offset_ms(store) / 1000.0  # latency calibration
        tapcheck = TapCheck(hub.publish)

        def vel_split() -> int:
            vr = (state["midi"].calibration() or {}).get("velocity_range") if "midi" in state else None
            return int((vr[0] + vr[1]) / 2) if vr and vr[1] > vr[0] else 64

        drill = Drill(hub.publish, vel_split=vel_split)
        intuition = Intuition(hub.publish)  # intuition exercises (PLAN 10), riyaz/intuition.py

        def sink(evt: dict) -> None:
            hub.publish(evt)  # the UI gets the key first (live keyboard)
            practice.on_midi(evt)  # then the wait-mode matcher (it can send practice events)
            drill.on_midi(evt)  # then the drill (keyboard basics, skill moments, "Find the key")
            intuition.on_midi(evt)  # then the intuition exercise (ear games)
            tapcheck.on_midi(evt)  # then the latency check ("tap with the click")
            if evt.get("type") == "note_on" and evt.get("reason") is None:
                activity.press()

        midi = MidiService(store, sink=sink, poll_interval=poll_interval)
        practice.midi = midi
        midi.echo_filter = practice.echo.is_echo  # song notes sent to the keyboard that come back
        intuition.midi = midi
        intuition.echo = practice.echo  # the same echo guard for the notes of the ear games
        state.update(midi=midi, practice=practice, drill=drill, tapcheck=tapcheck, intuition=intuition)
        state["audio"] = audio_import.AudioJobs(user_level=lambda: course.user_level())
        if start_midi:
            await asyncio.to_thread(midi.start)
            reminder.start()
        try:
            yield
        finally:
            reminder.stop()
            state["audio"].stop_all()
            activity.flush()
            await asyncio.to_thread(practice.close)
            await asyncio.to_thread(intuition.close)
            await asyncio.to_thread(midi.stop)
            await asyncio.to_thread(results.shutdown, True)
            store.close()

    def play_history(song_id: str) -> list[dict]:
        """Play-along attempts of a song (newest first), not the passes of a repeated part."""
        out = []
        for a in state["store"].attempts(kind="song", item=song_id, limit=60):
            d = a["data"] or {}
            if d.get("mode") == "play" and a["completed"] and isinstance(d.get("score"), dict) and not d.get("loop_pass"):
                out.append({"hands": a["hands"] or "", "section": a["section"], "span": d.get("span"),
                            "speed": a["speed"], "score": d["score"].get("total", 0), "range": d.get("range"),
                            "bar_errors": d.get("bar_errors") or {}})
        return out

    def after_play(evt: dict, result: dict) -> None:
        """Findings (PLAN 7.2) and automatic adapt (PLAN 7.3) of a play-along run."""
        song = course_mod.get_song(str(evt.get("song_id")))
        if song is None:
            return
        store = state["store"]
        unlocked = set(store.terms())
        hist = play_history(song["id"])  # hist[0] is this run (saved just before)
        alone = {}
        for h in hist:
            if h["hands"] in ("R", "L") and h["hands"] not in alone:
                alone[h["hands"]] = h["score"]
        vr = (state["midi"].calibration() or {}).get("velocity_range") if "midi" in state else None
        fb = feedback.analyze(song, evt, hist[1:], unlocked, vr, alone)
        result["findings"] = fb["findings"]
        result["all_findings"] = [f["id"] for f in fb["all"]]
        key = ("".join(evt.get("hands") or []), evt.get("section"), evt.get("span"))
        same = [h for h in hist if (h["hands"], h["section"], h["span"]) == key]
        adapt = None
        speed = float(evt.get("speed") or 1.0)
        if practice_options()["adapt"]:
            step = feedback.adapt(same, speed)
            if step and step["action"] in ("slower", "faster"):
                adapt = {**step, "text": feedback.render(feedback.adapt_text(step["action"], step["speed"]), unlocked)}
            elif step and step["action"] == "top":
                nxt = feedback.next_step(song, evt.get("hands") or [], evt.get("section"), evt.get("span"))
                adapt = {"action": "next", "speed": speed, "next": nxt, "text": feedback.render(nxt["text"], unlocked)}
        if result.get("learned"):
            text = feedback.render(feedback.ADAPT_TEXTS["learned"], unlocked)
            adapt = {**(adapt or {"action": "learned", "speed": speed}), "learned_text": text}
        result["adapt"] = adapt

    def on_practice_pass(evt: dict) -> None:
        """One pass of a repeated part (play-along): an attempt for the skill model and history."""
        try:
            state["course"].record_run({**evt, "completed": True, "loop_pass": True},
                                       session_id=state["sessions"].active_id)
        except Exception:
            log.exception("Cannot save the pass result")

    def on_practice_end(evt: dict) -> None:
        """A run ended: save it, update the course, tell the UI (event "course"). A play-along
        run also gets its findings and the automatic speed change."""
        try:
            c: Course = state["course"]
            result = c.record_run(evt, session_id=state["sessions"].active_id)
            if result is None:
                return
            if evt.get("mode") == "play":
                after_play(evt, result)
            if result.get("level_up"):
                # PLAN 8.4: after a level-up, a new easy version of the user's songs for the new level.
                try:
                    result["new_versions"] = simplify.new_versions_after_level_up(c.user_level())
                except Exception:
                    log.exception("Cannot make the easy versions")
                    result["new_versions"] = []
            unlocked = []
            if evt.get("song_id") in course_mod.content()["demo_songs"] and evt.get("completed"):
                done = c.complete_basics_task("b3-demo")
                unlocked = done["unlocked"]
                result["basics_done"] = done["basics_done"]
            hub.publish({"type": "course", "event": "run", "run": evt.get("run"), "unlocked": unlocked, **result})
        except Exception:
            log.exception("Cannot save the song result")

    app = FastAPI(lifespan=lifespan)
    # Starlette runs the last added middleware first: Host check, then Origin check.
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(config.ALLOWED_HOSTS))
    app.state.hub = hub
    app.state.latency = latency
    app.state.riyaz = state

    def midi() -> MidiService:
        return state["midi"]

    static = config.static_path()
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/api/state")
    async def get_state():
        return midi().status()

    @app.post("/api/ports/find")
    async def find_keyboard():
        return await asyncio.to_thread(midi().find_keyboard)

    @app.post("/api/ports/select")
    async def select_port(body: dict = Body(...)):
        try:
            return await asyncio.to_thread(midi().select_port, str(body.get("name", "")))
        except ValueError:
            raise HTTPException(404, "The app cannot find this keyboard. Click \"Find my keyboard\".")

    @app.post("/api/setup/{step}")
    async def start_step(step: str):
        if step == "cancel":
            midi().cancel_capture()
            return {"ok": True}
        try:
            midi().start_capture(step)
        except ValueError:
            raise HTTPException(404, "The app does not know this setup step.")
        return {"ok": True, "step": step}

    @app.post("/api/calibration/reset")
    async def reset_calibration():
        midi().reset_calibration()
        return midi().calibration()

    @app.post("/api/output/test-note")
    async def output_test_note():
        ok = await asyncio.to_thread(midi().play_test_note)
        return {"ok": ok}

    # ---------------------------------------------------------------- songs and practice (Phase 2)

    def practice() -> Practice:
        return state["practice"]

    def user_level() -> int:
        """The user's level from the course state (riyaz/course.py); 1 for a new user."""
        return state["course"].user_level() if "course" in state else config.USER_LEVEL_DEFAULT

    @app.get("/api/songs")
    async def list_songs():
        return {"songs": await asyncio.to_thread(songs.list_summaries, user_level()), "user_level": user_level()}

    @app.get("/api/songs/{song_id}")
    async def get_song(song_id: str):
        song = await asyncio.to_thread(course_mod.get_song, song_id)
        if song is None:
            raise HTTPException(404, "The app cannot find this song.")
        return song

    @app.get("/api/practice")
    async def practice_state():
        return practice().state()

    # One key activity at a time (practice, ear game, the "Find the key" drill, the tap check):
    # each start stops the others. Only active ones are stopped (no extra state events).

    def stop_others(keep: str, keep_practice: bool = False) -> None:
        if keep != "practice" and not keep_practice and "practice" in state and state["practice"].song is not None:
            state["practice"].stop()
        if keep != "drill" and "drill" in state and state["drill"].state().get("status") == "active":
            state["drill"].stop()
        if keep != "intuition" and "intuition" in state and \
                state["intuition"].state().get("status") not in ("idle", "done", "stopped"):
            state["intuition"].stop()
        if keep != "tapcheck" and "tapcheck" in state and state["tapcheck"].active:
            state["tapcheck"].cancel()

    # Practice calls can send MIDI (notes off) and wait for the MIDI thread: run them in a thread.

    @app.post("/api/practice/start")
    async def practice_start(body: dict = Body(...)):
        song = await asyncio.to_thread(course_mod.get_song, str(body.get("song_id", "")))
        if song is None:
            raise HTTPException(404, "The app cannot find this song.")
        output = body.get("output", "mac")
        if output == "keyboard" and midi().status()["output"] is None:
            raise HTTPException(409, "The app cannot send notes to the keyboard. "
                                     "Turn off \"Play the song on the keyboard speaker\".")
        hands = body.get("hands")
        opts = practice_options()
        practice().unlocked = set(await asyncio.to_thread(state["store"].terms))  # tip words (PLAN 7.4)
        await asyncio.to_thread(stop_others, "practice")
        try:
            return await asyncio.to_thread(
                practice().start,
                song, mode=body.get("mode", "wait"), hands=["R"] if hands is None else hands,
                speed=body.get("speed", 1.0), section=body.get("section"),
                count_in=bool(body.get("count_in", True)), accompany=bool(body.get("accompany", True)),
                output=output, breaks=body.get("breaks") if isinstance(body.get("breaks"), list) else None,
                loop=False if body.get("loop") is False else None, span=body.get("span"),
                adapt=opts["adapt"], loop_step=opts["loop_step"])
        except PracticeError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/practice/seek")
    async def practice_seek(body: dict = Body(...)):
        run = body.get("run")
        return await asyncio.to_thread(
            practice().seek, body.get("beat"), run=run if isinstance(run, int) and not isinstance(run, bool) else None,
            resume=body.get("resume", True) is not False)

    @app.post("/api/practice/pause")
    async def practice_pause(body: dict = Body(default={})):
        run = body.get("run")
        return await asyncio.to_thread(
            practice().pause, at_beat=body.get("at_beat"), reason=str(body.get("reason", "user"))[:20],
            run=run if isinstance(run, int) and not isinstance(run, bool) else None)

    @app.post("/api/practice/resume")
    async def practice_resume():
        return await asyncio.to_thread(practice().resume)

    @app.post("/api/practice/stop")
    async def practice_stop():
        return await asyncio.to_thread(practice().stop)

    @app.post("/api/practice/speed")
    async def practice_speed(body: dict = Body(...)):
        return await asyncio.to_thread(practice().set_speed, body.get("speed", 1.0))

    # ---------------------------------------------------------------- MIDI import (Phase 3a)
    # Step 1: POST the file bytes (body = the file, not a form). The app reads it and returns the
    # track list and a token. Step 2: POST the choices (tracks, swap hands, grid, title) with the
    # token. The app makes the song, saves it in the user data folder and returns the song card.
    # The Origin check (POST) protects both calls.

    pending: OrderedDict[str, midi_import.ParsedMidi] = OrderedDict()

    async def read_limited(request: Request, limit: int = config.IMPORT_MAX_BYTES) -> bytes:
        mb = limit // (1024 * 1024)
        too_large = f"The file is too large. The limit is {mb} MB. Select a smaller file."
        size = request.headers.get("content-length")
        if size is not None and size.isdigit() and int(size) > limit:
            raise HTTPException(413, too_large)
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, too_large)
            chunks.append(chunk)
        return b"".join(chunks)

    @app.post("/api/import/midi")
    async def import_midi_file(request: Request, name: str = "song.mid"):
        data = await read_limited(request)
        filename = name.replace("\\", "/").rsplit("/", 1)[-1][:120] or "song.mid"
        try:
            parsed = await asyncio.to_thread(midi_import.parse, data, filename)
        except midi_import.MidiImportError as exc:
            raise HTTPException(400, str(exc))
        token = secrets.token_hex(8)
        pending[token] = parsed
        while len(pending) > config.IMPORT_PENDING_MAX:
            pending.popitem(last=False)
        tracks = midi_import.track_list(parsed)
        return {"token": token, "file": filename, "title": midi_import.default_title(parsed),
                "tracks": tracks, "time_signature": list(parsed.time_signature)}

    @app.post("/api/import/midi/{token}/song")
    async def import_midi_song(token: str, body: dict = Body(...)):
        parsed = pending.get(token)
        if parsed is None:
            raise HTTPException(404, "The app cannot find the file. Select the file again.")
        quantize = body.get("quantize")
        title = body.get("title")
        try:
            song = await asyncio.to_thread(
                midi_import.build_song, parsed, parts=body.get("parts"), swap=body.get("swap") is True,
                quantize=quantize if quantize in config.IMPORT_QUANTIZE else None,
                title=title if isinstance(title, str) else None, user_level=user_level())
            await asyncio.to_thread(midi_import.save, song, parsed.data)
        except midi_import.MidiImportError as exc:
            raise HTTPException(400, str(exc))
        except OSError:
            log.exception("Cannot save the imported song")
            raise HTTPException(500, "The app cannot save the song. Make sure that the disk has free space.")
        return await asyncio.to_thread(imported_cards, song)

    def imported_cards(song: dict) -> dict:
        """The card of an imported song, and of its easy version for the user's level (PLAN 8.4)."""
        level = user_level()
        easy = None
        try:
            easy = simplify.ensure_level_version(song, level) or simplify.level_version(
                songs.load_all(), song["id"], level)
        except (simplify.SimplifyError, songs.SongError, OSError):
            log.exception("Cannot make the easy version")
        versions = simplify.versions_of(songs.load_all())
        return {"song": songs.summary(song, level, versions),
                "easy": songs.summary(easy, level, versions) if easy else None}

    # ---------------------------------------------------------------- simplifier (Phase 5a, PLAN 11.2, 8.4)

    @app.post("/api/songs/{song_id}/simplify")
    async def simplify_song(song_id: str, body: dict = Body(default={})):
        song = await asyncio.to_thread(songs.get, song_id)
        if song is None:
            raise HTTPException(404, "The app cannot find this song.")
        if song.get("version_of"):
            src = await asyncio.to_thread(songs.get, str(song["version_of"].get("id")))
            song = src or song
        level = user_level()

        target = body.get("level")  # tools and checks: a version for another level (1-10)
        target = target if isinstance(target, int) and not isinstance(target, bool) else None

        def run() -> dict:
            if body.get("for_level") is True or target is not None:
                v = simplify.for_level(song, target or level)
                if v is None:
                    raise simplify.SimplifyError("You can play this song now. The song needs no easy version.")
            else:
                v = simplify.make_version(song, left=str(body.get("left", "chords")), key=str(body.get("key", "same")),
                                          slow=body.get("slow") is True, change=str(body.get("change", "bar")))
            simplify.save(v)
            versions = simplify.versions_of(songs.load_all())
            return {"song": songs.summary(v, level, versions), "fits": v["level"] <= (target or level),
                    "user_level": level}

        try:
            return await asyncio.to_thread(run)
        except simplify.SimplifyError as exc:
            raise HTTPException(400, str(exc))
        except songs.SongError:
            log.exception("Easy version not valid")
            raise HTTPException(500, "The app cannot make an easy version of this song.")
        except OSError:
            log.exception("Cannot save the easy version")
            raise HTTPException(500, "The app cannot save the song. Make sure that the disk has free space.")

    # ---------------------------------------------------------------- song editor (Phase 5a, PLAN 11.4)

    @app.post("/api/editor/save")
    async def editor_save(body: dict = Body(...)):
        song_id = str(body.get("song_id", ""))
        try:
            song = await asyncio.to_thread(editor_mod.save, body.get("song"), song_id, body.get("copy") is True,
                                           user_level())
        except editor_mod.EditorError as exc:
            raise HTTPException(400, str(exc))
        except OSError:
            log.exception("Cannot save the edited song")
            raise HTTPException(500, "The app cannot save the song. Make sure that the disk has free space.")
        return {"song": song, "card": songs.summary(song, user_level()), "user_song": True}

    @app.get("/api/editor/{song_id}")
    async def editor_song(song_id: str):
        song = await asyncio.to_thread(songs.get, song_id)
        if song is None:
            raise HTTPException(404, "The app cannot find this song.")
        return {"song": song, "user_song": songs.is_user_song(song_id), "keys": list(editor_mod.KEY_NAMES)}

    # ---------------------------------------------------------------- audio import (Phase 5a, PLAN 11.3)

    def audio() -> audio_import.AudioJobs:
        return state["audio"]

    @app.get("/api/import/audio")
    async def audio_info():
        ok = audio_import.available()
        return {"available": ok, "text": None if ok else audio_import.NOT_AVAILABLE_TEXT,
                "max_mb": config.AUDIO_MAX_BYTES // (1024 * 1024), "max_minutes": config.AUDIO_MAX_SECONDS // 60}

    @app.post("/api/import/audio")
    async def audio_start(request: Request, name: str = "song.mp3"):
        filename = name.replace("\\", "/").rsplit("/", 1)[-1][:120] or "song.mp3"
        if not audio_import.available():
            raise HTTPException(400, audio_import.NOT_AVAILABLE_TEXT)
        data = await read_limited(request, config.AUDIO_MAX_BYTES)
        try:
            return await asyncio.to_thread(audio().start, data, filename)
        except audio_import.AudioImportError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/import/audio/{job_id}")
    async def audio_job(job_id: str):
        job = audio().get(job_id)
        if job is None:
            raise HTTPException(404, "The app cannot find this import. Select the file again.")
        return job

    @app.post("/api/import/audio/{job_id}/cancel")
    async def audio_cancel(job_id: str):
        job = await asyncio.to_thread(audio().cancel, job_id)
        if job is None:
            raise HTTPException(404, "The app cannot find this import. Select the file again.")
        return job

    # Practice options that stay after a restart (speed, the click, the count-in). One user.

    def practice_options() -> dict:
        saved = state["store"].get("practice.options", None)
        saved = saved if isinstance(saved, dict) else {}
        return {"speed": clamp_speed(saved.get("speed", 1.0)), "click": bool(saved.get("click", False)),
                "count_in": bool(saved.get("count_in", True)), "adapt": saved.get("adapt", True) is not False,
                "loop_step": saved.get("loop_step", True) is not False}

    @app.get("/api/settings/practice")
    async def get_practice_options():
        return practice_options()

    @app.post("/api/settings/practice")
    async def set_practice_options(body: dict = Body(...)):
        opts = practice_options()
        if "speed" in body:
            opts["speed"] = clamp_speed(body["speed"])
        for name in ("click", "count_in", "adapt", "loop_step"):
            if isinstance(body.get(name), bool):
                opts[name] = body[name]
        await asyncio.to_thread(state["store"].set, "practice.options", opts)
        return opts

    # Latency calibration: "tap with the click" (PLAN 4 Timing; riyaz/tapcheck.py).

    def latency_state() -> dict:
        ms = tapcheck_mod.offset_ms(state["store"])
        return {"offset_ms": ms, "done": state["store"].get(tapcheck_mod.KEY, None) is not None,
                "max_ms": config.TAP_MAX_S * 1000.0}

    @app.get("/api/settings/latency")
    async def get_latency_setting():
        return await asyncio.to_thread(latency_state)

    @app.post("/api/settings/latency/start")
    async def latency_check_start():
        await asyncio.to_thread(stop_others, "tapcheck")
        return state["tapcheck"].start()

    @app.post("/api/settings/latency/finish")
    async def latency_check_finish():
        res = state["tapcheck"].finish()
        if res.get("ok"):
            await asyncio.to_thread(state["store"].set, tapcheck_mod.KEY, res["offset_ms"])
            practice().input_offset_s = res["offset_ms"] / 1000.0
        return {**res, "text": tapcheck_mod.text_of(res), **(await asyncio.to_thread(latency_state))}

    @app.post("/api/settings/latency/reset")
    async def latency_reset():
        state["tapcheck"].cancel()
        await asyncio.to_thread(state["store"].set, tapcheck_mod.KEY, None)
        practice().input_offset_s = 0.0
        return await asyncio.to_thread(latency_state)

    # ---------------------------------------------------------------- course (Phase 3b)

    def course() -> Course:
        return state["course"]

    @app.get("/api/course")
    async def course_state():
        return await asyncio.to_thread(course().state)

    @app.get("/api/course/terms")
    async def course_terms():
        return await asyncio.to_thread(course().terms_state)

    @app.post("/api/course/terms/{term_id}/seen")
    async def course_term_seen(term_id: str):
        if not await asyncio.to_thread(course().term_seen, term_id):
            raise HTTPException(404, "You did not learn this word yet.")
        return {"ok": True}

    @app.get("/api/course/moments/{song_id}")
    async def course_moments(song_id: str):
        return {"moments": await asyncio.to_thread(course().pending_moments, song_id)}

    @app.get("/api/course/skills/{skill_id}")
    async def course_skill(skill_id: str):
        s = course().skill_public(skill_id)
        if s is None:
            raise HTTPException(404, "The app does not know this new skill.")
        return s

    @app.get("/api/course/skip/{level}")
    async def course_skip_info(level: int):
        try:
            return course().skip_info(level)
        except CourseError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/course/skip")
    async def course_skip(body: dict = Body(...)):
        try:
            return await asyncio.to_thread(course().skip_to, body.get("level"))
        except CourseError as exc:
            raise HTTPException(400, str(exc))

    # ---------------------------------------------------------------- drills (keyboard basics, skill
    # moments, warm-up, "Find the key"). The server makes the drill from the course content or the
    # session plan: the page only names it.

    def drill() -> Drill:
        return state["drill"]

    def drill_spec(body: dict) -> tuple[dict, int | None]:
        source = body.get("source")
        ref = body.get("ref")
        if source == "basics":
            task = next((t for t in course_mod.basics_tasks() if t["id"] == ref and "drill" in t), None)
            if task is None:
                raise HTTPException(404, "The app does not know this step of the keyboard basics.")
            return {**task["drill"], "id": f"basics:{ref}", "source": "basics", "ref": ref}, None
        if source == "skill":
            s = course().skill(str(ref))
            if s is None:
                raise HTTPException(404, "The app does not know this new skill.")
            return {"kind": "steps", "steps": s["steps"], "tries": s["tries"], "id": f"skill:{ref}",
                    "source": "skill", "ref": ref}, state["sessions"].active_id
        if source == "session":
            sid, index = body.get("session_id"), body.get("block")
            sess = state["store"].session(sid) if isinstance(sid, int) else None
            if sess is None or not isinstance(index, int) or not 0 <= index < len(sess["plan"]["blocks"]) \
                    or "drill" not in sess["plan"]["blocks"][index]:
                raise HTTPException(404, "The app cannot find this step of the practice.")
            return dict(sess["plan"]["blocks"][index]["drill"]), sid
        if source == "find_key":
            n = body.get("rounds")
            n = n if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 20 else config.FIND_KEY_ROUNDS
            return {"kind": "find_key", "id": "find_key", "rounds": n,
                    "source": "find_key"}, state["sessions"].active_id
        raise HTTPException(400, "The app does not know this exercise.")

    def drill_passed(spec: dict, summary: dict) -> dict:
        """Save the drill and do what it unlocks (it runs in the MIDI thread)."""
        c = course()
        extra: dict = {}
        if spec.get("source") == "basics":
            extra = c.complete_basics_task(spec["ref"])
        elif spec.get("source") == "skill":
            extra = c.complete_skill(spec["ref"], session_id=state["sessions"].active_id)
        state["store"].add_attempt(kind="drill", item=spec["id"].split(":")[0] if spec.get("source") != "skill"
                                   else spec["id"], day=course_mod.today(), session_id=state["sessions"].active_id,
                                   completed=True, wrong=summary["wrong"], data=summary)
        if spec.get("kind") == "find_key" and summary.get("times"):
            # Spaced repetition of "Find the key" (PLAN 9.3).
            review.record(state["store"], review.FIND_KEY, review.find_key_score(summary["times"], summary["wrong"]),
                          course_mod.today(), kind="drill", create=True)
        return extra

    @app.post("/api/drill/start")
    async def drill_start(body: dict = Body(...)):
        spec, _ = drill_spec(body)
        seed = body.get("seed")
        # One key activity at a time. A skill moment in a song keeps the paused song (it goes on after).
        await asyncio.to_thread(stop_others, "drill", spec.get("source") == "skill")
        try:
            return await asyncio.to_thread(drill().start, spec, drill_passed,
                                           seed if isinstance(seed, int) and not isinstance(seed, bool) else None)
        except DrillError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/drill/stop")
    async def drill_stop():
        return await asyncio.to_thread(drill().stop)

    @app.get("/api/drill")
    async def drill_state():
        return drill().state()

    # ---------------------------------------------------------------- intuition exercises (PLAN 10, Phase 5b)

    def intuition() -> Intuition:
        return state["intuition"]

    def intuition_done(spec: dict, summary: dict) -> dict:
        """Save the result (it runs in the MIDI or the intuition thread): the skill model reads it."""
        data = {k: v for k, v in summary.items() if isinstance(v, (int, float, str, bool, list, type(None)))}
        data["key"] = spec.get("key")
        state["store"].add_attempt(kind="intuition", item=spec["id"], day=course_mod.today(),
                                   session_id=state["sessions"].active_id, completed=True,
                                   accuracy=summary.get("score"), data=data)
        return {}

    def current_song_for_intuition(song_id=None) -> dict | None:
        song = course_mod.get_song(song_id) if isinstance(song_id, str) else None
        if song is None:
            settings = session_mod.habit_settings(state["store"])
            song = course_mod.get_song(settings["song_id"]) if settings["song_id"] else None
        if song is None or song.get("source") == "course":
            cur = course().current_song()
            song = course_mod.get_song(cur["song_id"]) if cur else None
        return song

    def intuition_spec(body: dict) -> dict:
        import random

        source = body.get("source", "intuition")
        seed = body.get("seed")
        rng = random.Random(seed if isinstance(seed, int) and not isinstance(seed, bool) else None)
        rounds = body.get("rounds") if isinstance(body.get("rounds"), int) and 1 <= body["rounds"] <= 12 else None
        if source == "session":
            sid, index = body.get("session_id"), body.get("block")
            sess = state["store"].session(sid) if isinstance(sid, int) else None
            if sess is None or not isinstance(index, int) or not 0 <= index < len(sess["plan"]["blocks"]) \
                    or "intuition" not in sess["plan"]["blocks"][index]:
                raise HTTPException(404, "The app cannot find this step of the practice.")
            b = sess["plan"]["blocks"][index]["intuition"]
            rng = random.Random(b.get("seed"))
            return intuition_mod.make_spec(b["id"], course(), rng, current_song_for_intuition(b.get("song_id")),
                                           source="session", ref=sid)
        ex_id = str(body.get("id", ""))
        ex = intuition_mod.exercise(ex_id)
        if ex is None or ex_id not in intuition_mod.KINDS:
            raise HTTPException(404, "The app does not know this exercise.")
        if ex["level"] > course().user_level():
            raise HTTPException(409, f"This exercise opens at Level {ex['level']}. Learn the songs before it first.")
        bars = body.get("bars") if isinstance(body.get("bars"), int) and 2 <= body["bars"] <= 16 else None
        return intuition_mod.make_spec(ex_id, course(), rng, current_song_for_intuition(body.get("song_id")),
                                       rounds=rounds, source="intuition", bars=bars)

    @app.get("/api/intuition")
    async def intuition_list():
        return {"exercises": await asyncio.to_thread(intuition_mod.public_list, course()),
                "level": course().user_level(), "state": intuition().state()}

    @app.get("/api/intuition/state")
    async def intuition_state():
        return intuition().state()

    @app.post("/api/intuition/start")
    async def intuition_start(body: dict = Body(...)):
        output = body.get("output", "mac")
        if output == "keyboard" and midi().status()["output"] is None:
            raise HTTPException(409, "The app cannot send notes to the keyboard. "
                                     "Turn off \"Play on the keyboard speaker\".")
        try:
            spec = await asyncio.to_thread(intuition_spec, body)
            await asyncio.to_thread(stop_others, "intuition")  # one key activity at a time
            return await asyncio.to_thread(intuition().start, spec, intuition_done, output)
        except IntuitionError as exc:
            raise HTTPException(400, str(exc))

    def run_of(body: dict):
        r = body.get("run")
        return r if isinstance(r, int) and not isinstance(r, bool) else None

    @app.post("/api/intuition/answer")
    async def intuition_answer(body: dict = Body(...)):
        try:
            return await asyncio.to_thread(intuition().answer, str(body.get("choice", "")), run_of(body))
        except IntuitionError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/intuition/replay")
    async def intuition_replay(body: dict = Body(default={})):
        try:
            return await asyncio.to_thread(intuition().replay, run_of(body))
        except IntuitionError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/intuition/tune-done")
    async def intuition_tune_done(body: dict = Body(default={})):
        try:
            return await asyncio.to_thread(intuition().tune_done, run_of(body))
        except IntuitionError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/intuition/stop")
    async def intuition_stop():
        return await asyncio.to_thread(intuition().stop)

    # ---------------------------------------------------------------- daily session and habit

    def sessions() -> Sessions:
        return state["sessions"]

    @app.get("/api/today")
    async def today_state():
        return await asyncio.to_thread(sessions().today)

    @app.get("/api/habit")
    async def habit_state():
        return await asyncio.to_thread(sessions().habit)

    @app.post("/api/session/start")
    async def session_start(body: dict = Body(default={})):
        return await asyncio.to_thread(sessions().start, body.get("minutes"))

    @app.post("/api/session/{session_id}/block")
    async def session_block(session_id: int, body: dict = Body(...)):
        try:
            return await asyncio.to_thread(sessions().block, session_id, body.get("index"), body.get("status"),
                                           body.get("seconds"), body.get("result"), body.get("paused"))
        except SessionError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/api/session/{session_id}/end")
    async def session_end(session_id: int):
        try:
            return await asyncio.to_thread(sessions().end, session_id)
        except SessionError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/settings/habit")
    async def get_habit_settings():
        return session_mod.habit_settings(state["store"])

    @app.post("/api/settings/habit")
    async def set_habit_settings(body: dict = Body(...)):
        return await asyncio.to_thread(session_mod.set_habit_settings, state["store"], body)

    @app.post("/api/habit/notify-test")
    async def notify_test():
        return {"ok": await asyncio.to_thread(session_mod.osascript_notify)}

    # ---------------------------------------------------------------- progress (Phase 4)

    def progress_data() -> dict:
        store = state["store"]
        unlocked = set(store.terms())
        per_song: dict[str, dict] = {}
        for a in reversed(store.attempts(kind="song", limit=2000)):
            d = a["data"] or {}
            mode = d.get("mode", "wait")
            if not a["completed"] or a["accuracy"] is None or d.get("loop_pass"):
                continue
            song = course_mod.get_song(a["item"])
            if song is None or song.get("source") == "course":
                continue
            entry = per_song.setdefault(a["item"], {"song_id": a["item"], "title": song["title"], "points": []})
            value = (d.get("score") or {}).get("total") if mode == "play" else a["accuracy"]
            if value is None:
                continue
            entry["points"].append({"t": a["t"], "day": a["day"], "mode": mode, "value": round(float(value), 1),
                                    "speed": a["speed"], "hands": a["hands"], "section": a["section"],
                                    "whole": a["section"] is None and not d.get("span")})
        reviews = []
        for r in store.reviews():
            song = course_mod.get_song(r["song_id"]) if r["song_id"] else None
            if r["kind"] == "section" and song is None:
                continue
            part = None
            if song and r["section"] is not None and r["section"] < len(song.get("sections") or []):
                part = song["sections"][r["section"]]["name"]
            reviews.append({"item": r["item"], "kind": r["kind"], "title": song["title"] if song else None,
                            "part": part, "due": r["due"], "interval": r["interval_days"], "last_score": r["last_score"]})
        return {"skills": skills_mod.model(store, unlocked), "songs": sorted(per_song.values(), key=lambda x: -x["points"][-1]["t"]),
                "reviews": reviews, "habit": state["sessions"].habit(), "today": course_mod.today()}

    @app.get("/api/progress")
    async def progress():
        return await asyncio.to_thread(progress_data)

    @app.get("/api/debug/latency")
    async def get_latency():
        return latency.summary()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if not origin_ok(ws.headers):
            log.warning("WebSocket from another origin blocked: %s", ws.headers.get("origin"))
            await ws.close(code=1008)  # policy violation
            return
        await ws.accept()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX)
        hub.queues.add(queue)
        put_drop_oldest(queue, json.dumps(midi().status()))

        async def writer():
            while True:
                await ws.send_text(await queue.get())

        task = asyncio.create_task(writer())
        try:
            while True:
                text = await ws.receive_text()
                try:
                    msg = json.loads(text)
                    if not isinstance(msg, dict):
                        continue
                    kind = msg.get("type")
                    if kind == "ping":
                        put_drop_oldest(queue, json.dumps(clock.pong(msg)))
                    elif kind == "latency_report":
                        latency.add(msg)
                except (ValueError, TypeError, AttributeError):
                    log.debug("Bad WebSocket message ignored: %.80r", text)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.queues.discard(queue)
            task.cancel()

    return app
