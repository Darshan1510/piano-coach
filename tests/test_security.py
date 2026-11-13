"""Host and Origin checks (DNS rebinding, cross-site requests) and bad WebSocket input."""

import asyncio

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from riyaz.server import Hub, create_app, put_drop_oldest

BASE = "http://127.0.0.1:8020"
WS = "ws://127.0.0.1:8020/ws"  # TestClient sends Host "testserver" for a bare "/ws"


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url=BASE) as c:
        c.app_ref = app
        yield c


def test_bad_host_rejected(client):
    assert client.get("/api/state", headers={"host": "evil.example:8020"}).status_code == 400
    assert client.get("/api/state", headers={"host": "localhost:8020"}).status_code == 200


def test_post_origin_check(client):
    url = "/api/setup/cancel"
    assert client.post(url).status_code == 200  # no Origin: Python tools, tests
    assert client.post(url, headers={"origin": BASE}).status_code == 200
    assert client.post(url, headers={"origin": "http://localhost:8020"}).status_code == 200
    for bad in ("http://evil.example", "http://127.0.0.1:9999", "null", "https://127.0.0.1:8020"):
        assert client.post(url, headers={"origin": bad}).status_code == 403, bad
    # GET is not state-changing: no Origin check.
    assert client.get("/api/state", headers={"origin": "http://evil.example"}).status_code == 200


def test_websocket_origin_check(client):
    with client.websocket_connect(WS) as ws:  # no Origin
        assert ws.receive_json()["type"] == "status"
    with client.websocket_connect(WS, headers={"origin": BASE}) as ws:
        assert ws.receive_json()["type"] == "status"
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(WS, headers={"origin": "http://evil.example"}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008


def test_websocket_ignores_bad_messages(client):
    with client.websocket_connect(WS) as ws:
        assert ws.receive_json()["type"] == "status"
        for text in ("not json", "[1, 2]", "42", "null", '{"type": "latency_report", "recv_ms": ["x"]}',
                     '{"type": "latency_report", "recv_ms": 5}'):
            ws.send_text(text)
        ws.send_json({"type": "ping", "id": 7, "t_client": 1.0})
        assert ws.receive_json()["id"] == 7  # the handler still runs
    assert client.get("/api/debug/latency").json()["recv"]["n"] == 0


def test_queue_drops_oldest_when_full():
    async def run():
        hub = Hub()
        q: asyncio.Queue = asyncio.Queue(maxsize=3)
        hub.queues.add(q)
        for i in range(5):
            hub._fanout(str(i))
        put_drop_oldest(q, "5")
        return [q.get_nowait() for _ in range(q.qsize())]

    assert asyncio.run(run()) == ["3", "4", "5"]
