"""HTTP + WebSocket tests (no CoreMIDI: MIDI start is off)."""

import mido
import pytest
from fastapi.testclient import TestClient

from riyaz.server import create_app


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:  # Host check: see test_security.py
        c.app_ref = app
        yield c


def test_index_and_static(client):
    r = client.get("/")
    assert r.status_code == 200 and "Riyaz" in r.text
    assert client.get("/static/app.js").status_code == 200
    tone = client.get("/static/vendor/tone.min.js")
    assert tone.status_code == 200 and len(tone.content) > 300_000
    mp3 = client.get("/static/samples/salamander/C4.mp3")
    assert mp3.status_code == 200 and len(mp3.content) > 10_000


def test_state(client):
    s = client.get("/api/state").json()
    assert s["type"] == "status" and s["connected"] is False


def test_setup_steps(client):
    assert client.post("/api/setup/middle_c").json()["ok"]
    assert client.post("/api/setup/cancel").json()["ok"]
    assert client.post("/api/setup/bogus").status_code == 404
    assert client.post("/api/ports/select", json={"name": "Nope"}).status_code == 404


def test_websocket_status_ping_and_events(client):
    midi = client.app_ref.state.riyaz["midi"]
    with client.websocket_connect("ws://127.0.0.1:8020/ws") as ws:  # Host check
        assert ws.receive_json()["type"] == "status"
        ws.send_json({"type": "ping", "id": 1, "t_client": 5.0})
        pong = ws.receive_json()
        assert pong["type"] == "pong" and pong["id"] == 1 and pong["t_server"] > 0
        midi.handle_message(mido.Message("note_on", note=60, velocity=70))
        evt = ws.receive_json()
        assert evt["type"] == "note_on" and evt["pitch"] == 60
        keys = ws.receive_json()
        assert keys["type"] == "keys" and keys["held"] == [60]
        ws.send_json({"type": "latency_report", "recv_ms": [1.0, 2.0], "paint_ms": [5.0, 6.0]})
        ws.send_json({"type": "ping", "id": 2, "t_client": 6.0})
        assert ws.receive_json()["id"] == 2
    lat = client.get("/api/debug/latency").json()
    assert lat["recv"]["n"] == 2 and lat["paint"]["median_ms"] == 5.5


def test_calibration_reset(client):
    midi = client.app_ref.state.riyaz["midi"]
    midi.set_calibration(-12, 0)
    r = client.post("/api/calibration/reset").json()
    assert r["offset"] == 0 and r["calibrated"] is False


def test_pedal_readout_hidden_by_default(client):
    # The user has no sustain pedal. The UI shows the pedal box only after the first CC 64.
    html = client.get("/").text
    assert 'id="pedal-box" class="readout-box small hidden"' in html
    js = client.get("/static/app.js").text
    assert '$("pedal-box").classList.remove("hidden")' in js
