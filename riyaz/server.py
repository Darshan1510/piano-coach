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

from . import clock, config
from .db import Store
from .midi_io import MidiService

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
        midi = MidiService(store, sink=hub.publish, poll_interval=poll_interval)
        state.update(store=store, midi=midi)
        if start_midi:
            await asyncio.to_thread(midi.start)
        try:
            yield
        finally:
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
            raise HTTPException(404, "Unknown step.")
        return {"ok": True, "step": step}

    @app.post("/api/calibration/reset")
    async def reset_calibration():
        midi().reset_calibration()
        return midi().calibration()

    @app.post("/api/output/test-note")
    async def output_test_note():
        ok = await asyncio.to_thread(midi().play_test_note)
        return {"ok": ok}

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
