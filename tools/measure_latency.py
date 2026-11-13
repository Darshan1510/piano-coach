"""Measure the delay from a key press to the app's WebSocket.

It opens the fake keyboard port, waits until the running app connects to it, plays N notes,
and listens on the app's WebSocket like the UI does.

  uv run tools/measure_latency.py                 # app at http://127.0.0.1:8020
  uv run tools/measure_latency.py --url http://127.0.0.1:8123 --count 200

Numbers (all on one clock, time.perf_counter):
  send->callback : fake port send -> rtmidi callback in the app (event field "t")
  send->ws       : fake port send -> this WebSocket client gets the event
  ui (if a window is open): the app UI's own report (callback -> WebSocket receipt / next frame)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.fake_player import PORT_NAME, FakePlayer  # noqa: E402


def _http(url: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="GET" if body is None else "POST")
    with urllib.request.urlopen(req, timeout=5) as res:
        return json.loads(res.read())


def summary(values_ms: list[float]) -> dict:
    v = sorted(values_ms)
    if not v:
        return {"n": 0}
    p95 = v[min(len(v) - 1, int(round(0.95 * (len(v) - 1))))]
    return {"n": len(v), "median_ms": round(statistics.median(v), 3), "p95_ms": round(p95, 3),
            "max_ms": round(v[-1], 3)}


def wait_connected(base: str, port_name: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _http(f"{base}/api/state")
        if state.get("port") == port_name:
            return state
        if port_name in state.get("inputs", []):
            return _http(f"{base}/api/ports/select", {"name": port_name})
        time.sleep(0.2)
    raise TimeoutError(f"The app did not see the port {port_name!r}")


async def measure(base: str, player: FakePlayer, count: int = 100, gap: float = 0.03,
                  shift_expected: int = 0) -> dict:
    ws_url = base.replace("http://", "ws://") + "/ws"
    send_to_cb: list[float] = []
    send_to_ws: list[float] = []
    wrong: list[tuple[int, int]] = []
    async with websockets.connect(ws_url) as ws:
        # Drain the first status message.
        await asyncio.wait_for(ws.recv(), 5)
        for i in range(count):
            pitch = 48 + (i % 25)
            t_send = player.note_on(pitch, 60 + i % 60)
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 2))
                if msg.get("type") == "note_on":
                    break
            t_recv = time.perf_counter()
            send_to_cb.append((msg["t"] - t_send) * 1000)
            send_to_ws.append((t_recv - t_send) * 1000)
            if msg["pitch"] != pitch + shift_expected:
                wrong.append((pitch, msg["pitch"]))
            player.note_off(pitch)
            await asyncio.sleep(gap)
    return {"send_to_callback": summary(send_to_cb), "send_to_ws": summary(send_to_ws),
            "wrong_pitch": wrong}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8020")
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--wait-ui", type=float, default=1.5, help="seconds to wait for the UI report")
    args = ap.parse_args()

    with FakePlayer(PORT_NAME) as player:
        state = wait_connected(args.url, PORT_NAME)
        print(f"App connected to: {state['port']}")
        result = asyncio.run(measure(args.url, player, args.count))
    time.sleep(args.wait_ui)
    try:
        result["ui"] = _http(f"{args.url}/api/debug/latency")
    except Exception as exc:  # noqa: BLE001
        result["ui"] = {"error": str(exc)}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
