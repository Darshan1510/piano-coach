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

from . import clock, config, course as course_mod, session as session_mod, songs
from .course import Course, CourseError
from .db import Store
from .drill import Drill, DrillError
from .importers import midi_import
from .midi_io import MidiService
from .practice import Practice, PracticeError, clamp_speed
from .session import Activity, Reminder, SessionError, Sessions

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

        practice = Practice(practice_sink)

        def vel_split() -> int:
            vr = (state["midi"].calibration() or {}).get("velocity_range") if "midi" in state else None
            return int((vr[0] + vr[1]) / 2) if vr and vr[1] > vr[0] else 64

        drill = Drill(hub.publish, vel_split=vel_split)

        def sink(evt: dict) -> None:
            hub.publish(evt)  # the UI gets the key first (live keyboard)
            practice.on_midi(evt)  # then the wait-mode matcher (it can send practice events)
            drill.on_midi(evt)  # then the drill (keyboard basics, skill moments, "Find the key")
            if evt.get("type") == "note_on" and evt.get("reason") is None:
                activity.press()

        midi = MidiService(store, sink=sink, poll_interval=poll_interval)
        practice.midi = midi
        midi.echo_filter = practice.echo.is_echo  # song notes sent to the keyboard that come back
        state.update(midi=midi, practice=practice, drill=drill)
        if start_midi:
            await asyncio.to_thread(midi.start)
            reminder.start()
        try:
            yield
        finally:
            reminder.stop()
            activity.flush()
            await asyncio.to_thread(practice.close)
            await asyncio.to_thread(midi.stop)
            await asyncio.to_thread(results.shutdown, True)
            store.close()

    def on_practice_end(evt: dict) -> None:
        """A wait-mode run ended: save it, update the course, tell the UI (event "course")."""
        try:
            c: Course = state["course"]
            result = c.record_run(evt, session_id=state["sessions"].active_id)
            if result is None:
                return
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
        try:
            return await asyncio.to_thread(
                practice().start,
                song, mode=body.get("mode", "wait"), hands=["R"] if hands is None else hands,
                speed=body.get("speed", 1.0), section=body.get("section"),
                count_in=bool(body.get("count_in", True)), accompany=bool(body.get("accompany", True)),
                output=output, breaks=body.get("breaks") if isinstance(body.get("breaks"), list) else None,
                loop=False if body.get("loop") is False else None)
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

    async def read_limited(request: Request) -> bytes:
        limit = config.IMPORT_MAX_BYTES
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
        return {"song": songs.summary(song, user_level())}

    # Practice options that stay after a restart (speed, the click, the count-in). One user.

    def practice_options() -> dict:
        saved = state["store"].get("practice.options", None)
        saved = saved if isinstance(saved, dict) else {}
        return {"speed": clamp_speed(saved.get("speed", 1.0)), "click": bool(saved.get("click", False)),
                "count_in": bool(saved.get("count_in", True))}

    @app.get("/api/settings/practice")
    async def get_practice_options():
        return practice_options()

    @app.post("/api/settings/practice")
    async def set_practice_options(body: dict = Body(...)):
        opts = practice_options()
        if "speed" in body:
            opts["speed"] = clamp_speed(body["speed"])
        for name in ("click", "count_in"):
            if isinstance(body.get(name), bool):
                opts[name] = body[name]
        await asyncio.to_thread(state["store"].set, "practice.options", opts)
        return opts

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
                raise HTTPException(404, "The app cannot find this part of the practice.")
            return dict(sess["plan"]["blocks"][index]["drill"]), sid
        if source == "find_key":
            return {"kind": "find_key", "id": "find_key", "rounds": config.FIND_KEY_ROUNDS,
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
        return extra

    @app.post("/api/drill/start")
    async def drill_start(body: dict = Body(...)):
        spec, _ = drill_spec(body)
        seed = body.get("seed")
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
