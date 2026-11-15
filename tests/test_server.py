"""HTTP + WebSocket tests (no CoreMIDI: MIDI start is off)."""

import re

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


# ---------------------------------------------------------------- Phase 2: songs and practice


def test_songs_api(client):
    songs = client.get("/api/songs").json()["songs"]
    ids = [s["id"] for s in songs]
    assert ids[:6] == ["mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle", "au-clair-de-la-lune",
                       "frere-jacques", "london-bridge"]
    song = client.get("/api/songs/ode-to-joy").json()
    assert song["notes"][0]["pitch"] == 64 and song["hand_positions"][0]["thumb_pitch"] == 60
    assert client.get("/api/songs/nope").status_code == 404


def test_practice_api_and_wait_events(client):
    midi = client.app_ref.state.riyaz["midi"]
    with client.websocket_connect("ws://127.0.0.1:8020/ws") as ws:
        assert ws.receive_json()["type"] == "status"
        s = client.post("/api/practice/start", json={"song_id": "mary-had-a-little-lamb", "mode": "wait",
                                                     "hands": ["R"], "count_in": False}).json()
        assert s["type"] == "practice" and s["running"] and s["hold_beat"] == 0.0 and s["expected"][0]["pitch"] == 64
        # wrong key: the UI gets note_on first, then practice_wrong; the song stays at stop 0
        midi.handle_message(mido.Message("note_on", note=65, velocity=70))
        kinds = []
        while "practice_wrong" not in kinds or "keys" not in kinds:
            kinds.append(ws.receive_json()["type"])
        kinds = [k for k in kinds if k != "practice"]  # clock states (start, waiting) can come between
        assert kinds[0] == "note_on" and sorted(kinds[1:]) == ["keys", "practice_wrong"]
        assert client.get("/api/practice").json()["stop_index"] == 0
        midi.handle_message(mido.Message("note_on", note=65, velocity=0))
        midi.handle_message(mido.Message("note_on", note=64, velocity=70))
        st = client.get("/api/practice").json()
        assert st["stop_index"] == 1 and st["wrong"] == 1
    p = client.post("/api/practice/pause", json={}).json()
    assert p["paused"] and not p["running"]
    assert client.post("/api/practice/resume").json()["running"]
    assert client.post("/api/practice/speed", json={"speed": 0.5}).json()["speed"] == 0.5
    assert client.post("/api/practice/stop").json()["song_id"] is None


def test_practice_start_errors(client):
    assert client.post("/api/practice/start", json={"song_id": "nope"}).status_code == 404
    r = client.post("/api/practice/start", json={"song_id": "ode-to-joy", "hands": ["L"]})
    assert r.status_code == 400
    # no MIDI output in this test: the keyboard sound is not possible
    r = client.post("/api/practice/start", json={"song_id": "ode-to-joy", "output": "keyboard"})
    assert r.status_code == 409 and "Play the song on the keyboard speaker" in r.json()["detail"]
    # a bad type is a bad request (400), not a server error (500)
    for body in ({"hands": 5}, {"hands": "R"}, {"hands": [None]}, {"mode": 3}, {"section": "x"}):
        r = client.post("/api/practice/start", json={"song_id": "ode-to-joy", **body})
        assert r.status_code == 400, (body, r.status_code)


def test_practice_options_are_kept(client):
    on = {"adapt": True, "loop_step": True}  # Phase 4: automatic speed changes, on by default (PLAN 7.3)
    assert client.get("/api/settings/practice").json() == {"speed": 1.0, "click": False, "count_in": True, **on}
    r = client.post("/api/settings/practice", json={"speed": 0.6, "click": True, "count_in": False}).json()
    assert r == {"speed": 0.6, "click": True, "count_in": False, **on}
    # bad values: speed is clamped, a non-bool is ignored
    r = client.post("/api/settings/practice", json={"speed": 99, "click": "yes", "adapt": "no", "loop_step": False}).json()
    assert r == {"speed": 1.5, "click": True, "count_in": False, "adapt": True, "loop_step": False}
    assert client.get("/api/settings/practice").json() == r
    store = client.app_ref.state.riyaz["store"]
    assert store.get("practice.options") == r  # in the settings database (stays after a restart)


def test_practice_post_needs_own_origin(client):
    r = client.post("/api/practice/start", json={"song_id": "ode-to-joy"},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


# PLAN 7.4: words that a Level 1-3 user has not learned yet. "s?" also finds the plural.
LOCKED = re.compile(r"\b(sharp|flat|major|minor|scale|interval|progression|bar|measure|beat|tempo|chord|"
                    r"rest)s?\b", re.I)
UI_FILES = ("/static/js/practice.js", "/static/js/songs.js", "/static/js/hands.js", "/static/app.js",
            "/static/js/importer.js", "/static/js/terms.js", "/static/js/drill.js", "/static/js/course.js",
            "/static/js/basics.js", "/static/js/today.js", "/static/js/renderer.js", "/static/js/keyboard.js",
            "/static/js/progress.js", "/static/js/editor.js", "/static/js/easy.js", "/static/js/intuition.js",
            "/static/js/recorder.js", "/static/js/coach.js")


def shown_strings(src: str) -> list[str]:
    """String literals in JS that can be user text. Comments are not shown.

    Allowed (code, not text): a string with no space that is all lower case, or that has "-", "_",
    "/", "." or "#" in it (ids, classes, event types, paths, keys like "minor").
    """
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)
    src = re.sub(r"\s//\s.*$", "", src, flags=re.M)  # comment at the end of a line
    out = []
    for a, b, c in re.findall(r'"([^"\n]*)"|`([^`]*)`|\'([^\'\n]*)\'', src):
        text = re.sub(r"\$\{[^}]*\}", " ", a or b or c)
        if " " not in text.strip() and (text == text.lower() or re.search(r"[-_/.#]", text)):
            continue
        out.append(text)
    return out


def test_practice_text_has_no_locked_words(client):
    """PLAN 7.4: no locked word in the HTML, the UI scripts or the backend messages for the user."""
    html = client.get("/").text
    html = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", html)
    attrs = " ".join(re.findall(r'(?:title|aria-label|placeholder|alt)="([^"]*)"', html))
    assert not LOCKED.search(visible), LOCKED.search(visible)
    assert not LOCKED.search(attrs), LOCKED.search(attrs)
    for js in UI_FILES:
        for text in shown_strings(client.get(js).text):
            assert not LOCKED.search(text), (js, text)
    for sid in ("mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle", "au-clair-de-la-lune",
                "frere-jacques", "london-bridge", "ode-to-joy-left-hand", "twinkle-twinkle-left-hand",
                "frere-jacques-both-hands", "basics-demo"):
        song = client.get(f"/api/songs/{sid}").json()
        text = " ".join([song["title"]] + [s["name"] for s in song["sections"]])
        assert not LOCKED.search(text), (sid, text)
    for text in backend_user_messages():
        assert not LOCKED.search(text), text
        assert text[0].isupper() and text.rstrip('"').endswith("."), text  # a full sentence


def backend_user_messages() -> list[str]:
    """Texts for the user in riyaz/ (all folders): PracticeError(...), HTTPException(...),
    MidiImportError(...), CourseError, DrillError and SessionError calls (the UI shows them).
    An f-string counts with its fixed parts."""
    import ast
    from pathlib import Path

    out = []
    for path in (Path(__file__).resolve().parent.parent / "riyaz").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in (
                    "PracticeError", "HTTPException", "MidiImportError", "CourseError", "DrillError",
                    "SessionError", "SimplifyError", "EditorError", "AudioImportError", "IntuitionError"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        out.append(arg.value)
                    elif isinstance(arg, ast.JoinedStr):
                        out.append("".join(v.value if isinstance(v, ast.Constant) else "N" for v in arg.values))
                    elif isinstance(arg, ast.BinOp):  # "a " "b" split over lines is one Constant; a + b is not used
                        pass
    # Phase 5a: the audio import texts are in a dict (riyaz/importers/audio_import.py).
    from riyaz.importers import audio_import

    out += [t.format(minutes=6) for t in audio_import.ERROR_TEXTS.values()] + [audio_import.NOT_AVAILABLE_TEXT]
    out += [f"Your song 'X' has a new version for your level.", "You can play the easy version now."]
    assert len(out) >= 25
    return out


def test_locked_word_check_finds_words():
    """The check itself: it finds locked words in text and skips code names."""
    assert shown_strings('a("chord-name"); b("minor"); c("Play the chord."); d(`Sharp ${x}`)') == [
        "Play the chord.", "Sharp  "]
    for word in ("bars", "Beat", "tempo", "F sharp", "flats", "minor", "scales", "rest"):
        assert LOCKED.search(word), word
    assert not LOCKED.search("sidebar rested barn")


# ---------------------------------------------------------------------------- MIDI import (Phase 3a)

from pathlib import Path  # noqa: E402

MIDI_DIR = Path(__file__).resolve().parent / "data" / "midi"


def test_import_midi_flow(client):
    data = (MIDI_DIR / "la-native.mid").read_bytes()
    r = client.post("/api/import/midi?name=la-native.mid", content=data,
                    headers={"Content-Type": "application/octet-stream", "Origin": "http://127.0.0.1:8020"})
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["file"] == "la-native.mid" and info["title"] == "La native"
    assert [(t["name"], t["note_count"], t["default"]) for t in info["tracks"]] == [("upper", 86, True), ("lower", 86, True)]
    r = client.post(f"/api/import/midi/{info['token']}/song", json={"parts": [0, 1], "swap": False, "quantize": 16,
                                                                   "title": "La Native"})
    assert r.status_code == 200, r.text
    card = r.json()["song"]
    assert card["source"] == "midi" and card["title"] == "La Native" and card["hands"] == ["R", "L"]
    # Phase 5a (PLAN 8.4): the song is too hard for Level 1, so the app made an easy version.
    assert card["difficulty"]["text"] == "You can play the easy version now."
    easy = r.json()["easy"]
    assert easy["version_of"]["id"] == card["id"] and easy["level"] <= 1 and card["easy"]["id"] == easy["id"]
    listed = client.get("/api/songs").json()
    assert listed["user_level"] == 1
    assert {s["id"] for s in listed["songs"][-2:]} == {card["id"], easy["id"]}
    song = client.get(f"/api/songs/{card['id']}").json()
    assert song["import"]["quantize"] == 16 and len(song["notes"]) == 172
    # The original file is kept next to the song.
    from riyaz import config

    assert (config.user_songs_path() / f"{card['id']}.mid").read_bytes() == data
    # The imported song starts in wait mode.
    r = client.post("/api/practice/start", json={"song_id": card["id"], "mode": "wait", "hands": ["R", "L"]})
    assert r.status_code == 200 and r.json()["song_id"] == card["id"]
    client.post("/api/practice/stop", json={})


def test_import_errors(client):
    r = client.post("/api/import/midi?name=x.txt", content=b"hello")
    assert r.status_code == 400 and r.json()["detail"].startswith("This file is not a MIDI file.")
    r = client.post("/api/import/midi", content=b"")
    assert r.status_code == 400 and "empty" in r.json()["detail"]
    from riyaz import config

    r = client.post("/api/import/midi", content=b"MThd" + b"0" * config.IMPORT_MAX_BYTES)
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    r = client.post("/api/import/midi/nope/song", json={"parts": [0]})
    assert r.status_code == 404 and r.json()["detail"] == "The app cannot find the file. Select the file again."
    data = (MIDI_DIR / "la-native.mid").read_bytes()
    token = client.post("/api/import/midi", content=data).json()["token"]
    r = client.post(f"/api/import/midi/{token}/song", json={"parts": []})
    assert r.status_code == 400 and r.json()["detail"] == "Select one or more tracks."
    r = client.post(f"/api/import/midi/{token}/song", json={"parts": [5]})
    assert r.status_code == 400


def test_import_post_needs_own_origin(client):
    data = (MIDI_DIR / "la-native.mid").read_bytes()
    r = client.post("/api/import/midi", content=data, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    token = client.post("/api/import/midi", content=data).json()["token"]
    r = client.post(f"/api/import/midi/{token}/song", json={"parts": [0]}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_import_pending_files_are_limited(client):
    from riyaz import config

    data = (MIDI_DIR / "synthetic" / "drums.mid").read_bytes()
    tokens = [client.post("/api/import/midi", content=data).json()["token"] for _ in range(config.IMPORT_PENDING_MAX + 2)]
    assert client.post(f"/api/import/midi/{tokens[0]}/song", json={"parts": [0]}).status_code == 404
    assert client.post(f"/api/import/midi/{tokens[-1]}/song", json={"parts": [0]}).status_code == 200


def test_imported_song_text_has_no_locked_words(client):
    for name in ("la-native.mid", "les-graces-one-track.mid", "synthetic/drums.mid"):
        data = (MIDI_DIR / name).read_bytes()
        token = client.post(f"/api/import/midi?name={Path(name).name}", content=data).json()["token"]
        card = client.post(f"/api/import/midi/{token}/song", json={"parts": [0]}).json()["song"]
        song = client.get(f"/api/songs/{card['id']}").json()
        text = " ".join([card["difficulty"]["text"], card["title"]] + [s["name"] for s in song["sections"]])
        assert not LOCKED.search(text), text
