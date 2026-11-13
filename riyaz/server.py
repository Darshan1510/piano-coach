"""FastAPI app: static UI, REST calls for setup, and the WebSocket that carries MIDI events."""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import PlainTextResponse

from . import clock, config, songs
from .db import Store
from .midi_io import MidiService
from .practice import Practice, PracticeError, clamp_speed

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
        practice = Practice(hub.publish)

        def sink(evt: dict) -> None:
            hub.publish(evt)  # the UI gets the key first (live keyboard)
            practice.on_midi(evt)  # then the wait-mode matcher (it can send practice events)

        midi = MidiService(store, sink=sink, poll_interval=poll_interval)
        practice.midi = midi
        midi.echo_filter = practice.echo.is_echo  # song notes sent to the keyboard that come back
        state.update(store=store, midi=midi, practice=practice)
        if start_midi:
            await asyncio.to_thread(midi.start)
        try:
            yield
        finally:
            await asyncio.to_thread(practice.close)
            await asyncio.to_thread(midi.stop)
            store.close()

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

    @app.get("/api/songs")
    async def list_songs():
        return {"songs": await asyncio.to_thread(songs.list_summaries)}

    @app.get("/api/songs/{song_id}")
    async def get_song(song_id: str):
        song = await asyncio.to_thread(songs.get, song_id)
        if song is None:
            raise HTTPException(404, "The app cannot find this song.")
        return song

    @app.get("/api/practice")
    async def practice_state():
        return practice().state()

    # Practice calls can send MIDI (notes off) and wait for the MIDI thread: run them in a thread.

    @app.post("/api/practice/start")
    async def practice_start(body: dict = Body(...)):
        song = await asyncio.to_thread(songs.get, str(body.get("song_id", "")))
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
                output=output)
        except PracticeError as exc:
            raise HTTPException(400, str(exc))

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
