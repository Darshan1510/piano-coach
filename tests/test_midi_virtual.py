"""Tests with real CoreMIDI virtual ports (tools/fake_player.py). Skipped if CoreMIDI is not there."""

import asyncio
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.fake_player import FakePlayer  # noqa: E402
from tools.measure_latency import measure, wait_connected  # noqa: E402

from riyaz.db import Store  # noqa: E402
from riyaz.midi_io import MidiService  # noqa: E402
from riyaz.server import create_app  # noqa: E402

PORT = "Riyaz Test Keyboard"
# A second port, like the user's real USB-MIDI keyboard. The port filter must hide it.
OTHER_PORT = "USB MIDI Interface (test stand-in)"


def _virtual_ok():
    try:
        p = FakePlayer("Riyaz Probe")
        p.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not _virtual_ok(), reason="needs CoreMIDI virtual ports")


@pytest.fixture(autouse=True)
def only_test_port(monkeypatch):
    """The app sees only the test port, also when a real keyboard is plugged in."""
    monkeypatch.setenv("RIYAZ_PORT_FILTER", PORT)


def wait_for(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Collector:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, evt):
        with self.lock:
            self.events.append(evt)

    def of(self, kind):
        with self.lock:
            return [e for e in self.events if e["type"] == kind]


@pytest.fixture
def service(store):
    col = Collector()
    svc = MidiService(store, sink=col, poll_interval=0.2)
    svc.collector = col
    yield svc
    svc.stop()


def test_notes_arrive_from_virtual_port(service):
    with FakePlayer(PORT) as fp:
        service.start()
        assert wait_for(lambda: PORT in service.inputs, 3)
        service.select_port(PORT)
        fp.play([(60, 0.2), (64, 0.2), (67, 0.2)], bpm=600, noise=True)
        assert wait_for(lambda: len(service.collector.of("note_off")) >= 3)
    ons = [e["pitch"] for e in service.collector.of("note_on")]
    # Before calibration all channels pass, so the noise note 48 (channel 10) also comes in.
    assert [p for p in ons if p != 48] == [60, 64, 67]


def test_calibration_with_shift_plus_12(service, store):
    with FakePlayer(PORT, shift=12) as fp:
        service.start()
        assert wait_for(lambda: PORT in service.inputs, 3)
        service.select_port(PORT)
        service.start_capture("middle_c")
        fp.tap(60, 0.05)  # user presses middle C; keyboard sends 72
        assert wait_for(lambda: service.collector.of("calibration"))
        assert store.get("calibration.offset") == -12
        service.collector.events.clear()
        melody = [60, 62, 64, 65, 67, 69, 71, 72]
        fp.play([(p, 0.1) for p in melody], bpm=600, noise=True)  # noise: other channel must be dropped
        assert wait_for(lambda: len(service.collector.of("note_off")) >= len(melody))
    assert [e["pitch"] for e in service.collector.of("note_on")] == melody
    assert [e["raw"] for e in service.collector.of("note_on")] == [p + 12 for p in melody]


def test_port_filter_hides_other_ports(service):
    with FakePlayer(OTHER_PORT), FakePlayer(PORT):
        service.start()
        assert wait_for(lambda: service.connected, 3)
        assert service.inputs == [PORT] and service.port_name == PORT


def test_hotplug_virtual_port_appears_and_disappears(service):
    other = FakePlayer(OTHER_PORT)  # the user's real keyboard is often plugged in
    service.start()
    col = service.collector
    assert not service.connected
    fp = FakePlayer(PORT)
    try:
        assert wait_for(lambda: service.connected and service.port_name == PORT, 3), "port did not appear"
        fp.note_on(60)
        assert wait_for(lambda: col.of("note_on"))
    finally:
        fp.close()  # key 60 is still down: the app must release it
    assert wait_for(lambda: not service.connected, 3), "unplug not seen"
    assert any(e.get("reason") == "disconnect" and e["pitch"] == 60 for e in col.of("note_off"))
    fp = FakePlayer(PORT)
    try:
        assert wait_for(lambda: service.connected, 3), "re-plug not seen"
        fp.note_on(62)
        assert wait_for(lambda: col.of("note_on")[-1]["pitch"] == 62)
        fp.note_off(62)
    finally:
        fp.close()
        other.close()


@pytest.fixture
def live_server(data_dir):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(poll_interval=0.2)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    assert wait_for(lambda: server.started, 10)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def test_end_to_end_latency_under_20ms(live_server):
    """Fake port -> WebSocket. A busy machine can give one slow run, so one retry is allowed.

    The acceptance number in PROGRESS.md is the UI paint delay (About screen), not this test.
    """
    def fast(r):
        return r["send_to_ws"]["median_ms"] < 20 and r["send_to_ws"]["p95_ms"] < 20

    with FakePlayer(PORT) as fp:
        wait_connected(live_server, PORT)
        result = asyncio.run(measure(live_server, fp, count=200, gap=0.01))
        if not fast(result):
            print("\nLATENCY (slow, retry)", json.dumps(result))
            result = asyncio.run(measure(live_server, fp, count=200, gap=0.01))
    print("\nLATENCY", json.dumps(result))
    assert result["wrong_pitch"] == []
    assert fast(result), result["send_to_ws"]


def _get_state(base):
    import urllib.request

    with urllib.request.urlopen(f"{base}/api/state", timeout=2) as r:
        return json.loads(r.read())


def test_hotplug_cross_process_real_app(data_dir):
    """Real app process (main.py --server) + fake keyboard in another process.

    This is the real case: a keyboard that appears after the app started. In Phase 1 this
    test found that a CoreMIDI port list from the wrong thread never changes.
    """
    import os
    import subprocess

    root = Path(__file__).resolve().parent.parent
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, RIYAZ_DATA_DIR=str(data_dir), PORT=str(port), RIYAZ_PORT_FILTER=PORT)
    other = FakePlayer(OTHER_PORT)  # stand-in for a real keyboard: the filter hides it
    app = subprocess.Popen([sys.executable, "main.py", "--server"], cwd=root, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    fake = [sys.executable, "tools/fake_player.py", "--name", PORT, "--wait", "0", "--notes", "60",
            "--bpm", "600", "--hold"]
    try:
        assert wait_for(lambda: _try(lambda: _get_state(base)), 15), "app did not start"
        assert not _get_state(base)["connected"]
        times = []
        for _ in range(2):  # plug in, unplug, plug in again, unplug
            t0 = time.monotonic()
            p = subprocess.Popen(fake + ["6"], cwd=root, stdout=subprocess.DEVNULL)
            try:
                assert wait_for(lambda: _get_state(base)["port"] == PORT, 6), "plug-in not seen"
                times.append(round(time.monotonic() - t0, 2))
            finally:
                p.wait(10)
            assert wait_for(lambda: not _get_state(base)["connected"], 6), "unplug not seen"
        print("\nHOTPLUG seen after (s):", times)
    finally:
        app.terminate()
        app.wait(10)
        other.close()


def _try(fn):
    try:
        return fn()
    except Exception:
        return None


def test_wait_mode_end_to_end_with_fake_player(live_server):
    """Phase 2 acceptance 2 + 3 with real CoreMIDI: the fake player completes a song in wait mode;
    a wrong key does not advance the song. (All 6 songs: `tools/fake_player.py --song all --follow`.)"""
    from tools.fake_player import follow_wait

    with FakePlayer(PORT) as fp:
        wait_connected(live_server, PORT)
        r = asyncio.run(follow_wait(live_server, fp, "london-bridge", ("R",), speed=1.5, wrong=2, timeout=30))
    print("\nWAIT MODE", json.dumps(r))
    assert r["completed"] and r["stops"] == 24 and r["hits"] == 24
    assert r["wrong_events"] == 2 and r["wrong_reported"] == 2 and r["advanced_on_wrong"] == 0
