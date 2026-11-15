"""Phase 5a: audio import (PLAN 11.3). The worker tests need the audio packages (uv group "audio");
they skip without them. The other tests (file checks, notes -> song, no audio packages) always run."""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from riyaz import config, songs
from riyaz.importers import audio_import
from riyaz.server import create_app
from tools import make_test_audio

AUDIO = Path(__file__).resolve().parent / "data" / "audio"
RECORDING = AUDIO / "beethoven-minuet-in-g-musopen.mp3"
needs_audio = pytest.mark.skipif(not audio_import.available(), reason="audio packages (uv group audio) not installed")


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        c.riyaz = app.state.riyaz
        yield c


def note_accuracy(found: list[list[float]], truth: list[dict], tol: float = 0.05) -> dict:
    """Note precision/recall/F1: the same key and the start within tol seconds (one to one)."""
    used = set()
    hit = 0
    for t in truth:
        best = None
        for i, f in enumerate(found):
            if i in used or int(f[2]) != t["pitch"]:
                continue
            d = abs(f[0] - t["onset"])
            if d <= tol and (best is None or d < best[0]):
                best = (d, i)
        if best:
            used.add(best[1])
            hit += 1
    p = hit / len(found) if found else 0.0
    r = hit / len(truth) if truth else 0.0
    return {"hit": hit, "found": len(found), "truth": len(truth), "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r else 0.0}


# ------------------------------------------------------------------------- always (no model)


def test_file_checks():
    with pytest.raises(audio_import.AudioImportError, match="Select an MP3, WAV or M4A file."):
        audio_import.check_file(b"x", "a.ogg")
    with pytest.raises(audio_import.AudioImportError, match="empty"):
        audio_import.check_file(b"", "a.wav")
    with pytest.raises(audio_import.AudioImportError, match="not a correct"):
        audio_import.check_file(b"hello world!", "a.wav")
    assert audio_import.check_file(b"RIFF\0\0\0\0WAVEfmt ", "a.WAV") == ".wav"
    assert audio_import.check_file(b"ID3\x04" + b"\0" * 10, "a.mp3") == ".mp3"
    assert audio_import.check_file(b"\0\0\0\x20ftypM4A ", "a.m4a") == ".m4a"
    big = b"RIFF\0\0\0\0WAVE" + b"\0" * config.AUDIO_MAX_BYTES
    with pytest.raises(audio_import.AudioImportError, match="too large"):
        audio_import.check_file(big, "a.wav")


def test_bpm_offset_and_notes_to_song():
    assert audio_import.song_bpm(240) == 120 and audio_import.song_bpm(40) == 80 and audio_import.song_bpm(0) == 100
    assert audio_import.beat_offset([1.0, 1.5], 0.2, 0.5) == pytest.approx(0.0)
    notes = [[0.5 + i * 0.5, 0.95 + i * 0.5, p, 90] for i, p in enumerate([60, 62, 64, 65, 67, 65, 64, 62])]
    song, midi = audio_import.build_song({"notes": notes, "bpm": 120, "beats": [0.5, 1.0, 1.5]}, "my tune.wav", 1)
    assert song["source"] == "audio" and song["title"] == "My tune" and len(song["notes"]) == 8
    assert [n["pitch"] for n in song["notes"]] == [60, 62, 64, 65, 67, 65, 64, 62]
    assert [n["start"] for n in song["notes"]] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert midi[:4] == b"MThd" and song["import"]["audio"]["notes"] == 8
    with pytest.raises(audio_import.AudioImportError, match="no notes"):
        audio_import.build_song({"notes": [], "bpm": 100}, "x.wav", 1)


def test_worker_command_has_no_shell():
    cmd = audio_import.worker_command(Path("/a b/in.wav"), Path("/a b/out.json"))
    assert cmd[0] == sys.executable and cmd[1:3] == ["-m", "riyaz.importers.audio_worker"]
    assert cmd[3] == "/a b/in.wav"  # one argument, spaces kept


def test_no_audio_packages_gives_a_plain_message(client, monkeypatch):
    monkeypatch.setattr(audio_import, "available", lambda: False)
    info = client.get("/api/import/audio").json()
    assert info["available"] is False and info["text"] == audio_import.NOT_AVAILABLE_TEXT
    r = client.post("/api/import/audio?name=a.wav", content=b"RIFF\0\0\0\0WAVE")
    assert r.status_code == 400 and r.json()["detail"] == audio_import.NOT_AVAILABLE_TEXT


def test_base_app_does_not_import_the_audio_packages():
    """The app starts without the audio stack: no audio package is loaded at import time."""
    code = ("import sys; import riyaz.server, riyaz.importers.audio_import; "
            "bad = [m for m in ('basic_pitch', 'librosa', 'numpy', 'scipy', 'coremltools') if m in sys.modules]; "
            "print(bad); sys.exit(1 if bad else 0)")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       cwd=str(Path(__file__).resolve().parent.parent))
    assert r.returncode == 0, r.stdout + r.stderr


def test_stage_texts_have_no_locked_words():
    from tests.test_server import LOCKED

    for text in list(audio_import.AudioJobs.STAGES.values()) + list(audio_import.ERROR_TEXTS.values()):
        assert not LOCKED.search(text), text


def test_audio_errors_through_the_server(client):
    if not audio_import.available():
        pytest.skip("audio packages not installed")
    r = client.post("/api/import/audio?name=a.ogg", content=b"OggS")
    assert r.status_code == 400 and r.json()["detail"] == "Select an MP3, WAV or M4A file."
    assert client.get("/api/import/audio/nope").status_code == 404
    assert client.post("/api/import/audio/nope/cancel").status_code == 404
    r = client.post("/api/import/audio?name=a.wav", content=b"RIFF", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


# ------------------------------------------------------------------------- with the model


def wait_job(client, job_id, timeout=300):
    end = time.monotonic() + timeout
    stages = []
    while time.monotonic() < end:
        job = client.get(f"/api/import/audio/{job_id}").json()
        if not stages or stages[-1] != job["stage"]:
            stages.append(job["stage"])
        if job["state"] != "running":
            return job, stages
        time.sleep(0.2)
    raise AssertionError("audio import did not end")


@needs_audio
def test_synthesized_wav_note_accuracy(tmp_path):
    """The worker on a WAV made from Ode to Joy (known notes): note accuracy (same key, start
    within 50 ms)."""
    wav = tmp_path / "ode.wav"
    truth = make_test_audio.make(songs.get("ode-to-joy"), wav, "R")
    out = tmp_path / "out.json"
    r = subprocess.run(audio_import.worker_command(wav, out), capture_output=True, text=True, timeout=300,
                       cwd=str(config.base_path()))
    assert r.returncode == 0, r.stderr[-2000:]
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    assert lines[0]["stage"] == "load" and lines[-1]["stage"] == "done"
    assert any(x["stage"] == "notes" and 0 < x["progress"] < 1 for x in lines)
    res = json.loads(out.read_text())
    acc = note_accuracy(res["notes"], truth)
    print("synth accuracy", acc, "bpm", res["bpm"], "seconds", res["seconds"])
    assert acc["f1"] >= 0.9, acc
    assert 85 <= audio_import.song_bpm(res["bpm"]) <= 95  # the song is at 90


@needs_audio
def test_m4a_import_through_the_server(client, tmp_path):
    """M4A -> WAV with afconvert, then the whole import; the easy version is made."""
    if not Path(config.AFCONVERT).exists():
        pytest.skip("no afconvert")
    wav = tmp_path / "twinkle.wav"
    make_test_audio.make(songs.get("twinkle-twinkle"), wav, "R")
    m4a = tmp_path / "twinkle.m4a"
    subprocess.run([config.AFCONVERT, "-f", "m4af", "-d", "aac", str(wav), str(m4a)], check=True)
    r = client.post("/api/import/audio?name=twinkle.m4a", content=m4a.read_bytes())
    assert r.status_code == 200, r.text
    job, stages = wait_job(client, r.json()["id"])
    assert job["state"] == "done", job
    assert "notes" in stages
    song = songs.get(job["song"]["id"])
    assert song["source"] == "audio" and len(song["notes"]) >= 35  # 42 notes in the song
    assert (config.user_songs_path() / f"{song['id']}.mid").is_file()
    assert not any(config.audio_tmp_path().iterdir()) if config.audio_tmp_path().exists() else True


@needs_audio
def test_cancel_stops_the_worker(client):
    r = client.post("/api/import/audio?name=minuet.mp3", content=RECORDING.read_bytes())
    job_id = r.json()["id"]
    for _ in range(200):
        if client.get(f"/api/import/audio/{job_id}").json()["stage"] in ("load", "notes"):
            break
        time.sleep(0.05)
    client.post(f"/api/import/audio/{job_id}/cancel")
    job, _ = wait_job(client, job_id, 60)
    assert job["state"] == "cancelled" and job["error"] == "You stopped the import."


@needs_audio
def test_public_domain_recording_gives_an_editable_song(client):
    """Acceptance 2: the public-domain recording -> a song that opens in the editor, saves, and
    plays in wait mode."""
    t0 = time.monotonic()
    r = client.post("/api/import/audio?name=beethoven-minuet-in-g-musopen.mp3", content=RECORDING.read_bytes())
    assert r.status_code == 200, r.text
    job, stages = wait_job(client, r.json()["id"], 600)
    took = time.monotonic() - t0
    assert job["state"] == "done", job
    print("recording: notes", job["note_count"], "worker s", job["seconds"], "total s", round(took, 1),
          "duration", job["duration"], "bpm", job["bpm"], "easy level", job["easy"] and job["easy"]["level"])
    assert job["note_count"] > 200 and job["easy"] is not None
    target = job["easy"]["id"]
    ed = client.get(f"/api/editor/{target}").json()
    assert ed["user_song"] is True
    song = ed["song"]
    payload = {k: song[k] for k in ("title", "bpm", "key", "time_signature", "notes", "sections")}
    payload["notes"] = [dict(n) for n in song["notes"]]
    payload["notes"][0]["pitch"] = min(96, payload["notes"][0]["pitch"] + 1)
    payload["notes"][0]["finger"] = None
    r = client.post("/api/editor/save", json={"song_id": target, "song": payload})
    assert r.status_code == 200, r.text
    r = client.post("/api/practice/start", json={"song_id": target, "mode": "wait", "hands": songs.hands_of(r.json()["song"])})
    assert r.status_code == 200
    client.post("/api/practice/stop", json={})


# ------------------------------------------------------------------- Phase 5 review fixes (A8, A9)

SLOW_WORKER = ("import json, sys, time; print(json.dumps({'stage': 'load', 'progress': 0}), flush=True); "
               "time.sleep(120)")


@pytest.fixture
def slow_worker(monkeypatch):
    """A worker that never ends (no model needed): for the busy and cancel checks."""
    monkeypatch.setattr(audio_import, "available", lambda: True)
    monkeypatch.setattr(audio_import, "worker_command", lambda i, o: [sys.executable, "-c", SLOW_WORKER])


def _running_proc(client, job_id):
    jobs = client.riyaz["audio"]
    for _ in range(200):
        proc = jobs.procs.get(job_id)
        if proc is not None:
            return proc
        time.sleep(0.05)
    raise AssertionError("the worker did not start")


def test_one_import_at_a_time_and_cancel_ends_the_process(client, slow_worker):
    data = RECORDING.read_bytes()
    r = client.post("/api/import/audio?name=a.mp3", content=data)
    assert r.status_code == 200, r.text
    job_id = r.json()["id"]
    proc = _running_proc(client, job_id)
    busy = client.post("/api/import/audio?name=b.mp3", content=data)
    assert busy.status_code == 400 and busy.json()["detail"] == "Wait for the import to finish."
    client.post(f"/api/import/audio/{job_id}/cancel")
    job, _ = wait_job(client, job_id, 30)
    assert job["state"] == "cancelled"
    assert proc.wait(timeout=10) is not None  # the process ended
    # A new import can start now.
    r = client.post("/api/import/audio?name=c.mp3", content=data)
    assert r.status_code == 200
    _running_proc(client, r.json()["id"])
    client.post(f"/api/import/audio/{r.json()['id']}/cancel")
    wait_job(client, r.json()["id"], 30)


def test_worker_env_has_the_numba_cache_in_the_data_folder(data_dir):
    env = audio_import.worker_env()
    assert env["NUMBA_CACHE_DIR"] == str(data_dir / "cache" / "numba")
    assert (data_dir / "cache" / "numba").is_dir()


def test_old_temp_audio_files_go_away_at_the_start(data_dir):
    old = config.audio_tmp_path() / "deadbeef"
    old.mkdir(parents=True)
    (old / "input.mp3").write_bytes(b"x")
    audio_import.AudioJobs()
    assert not config.audio_tmp_path().exists()


def test_worker_stops_when_the_app_process_stops(tmp_path):
    """The worker watches its parent process: when the parent stops, the worker stops."""
    pid_file = tmp_path / "pid"
    child = ("import time; from riyaz.importers.audio_worker import watch_parent; watch_parent(0.1); "
             "time.sleep(60)")
    parent = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', sys.argv[1]]); "
              "open(sys.argv[2], 'w').write(str(p.pid)); import time; time.sleep(1)")
    subprocess.run([sys.executable, "-c", parent, child, str(pid_file)], check=True, timeout=30,
                   cwd=str(config.base_path()))
    pid = int(pid_file.read_text())
    import os

    end = time.monotonic() + 15
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    os.kill(pid, 9)
    raise AssertionError("the worker did not stop")
