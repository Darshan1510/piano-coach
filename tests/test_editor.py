"""Phase 5a: song editor (PLAN 11.4). API-level tests of the edit operations: the page sends the
changed song to /api/editor/save; the app checks it, gives fingers to new notes, makes the hand
positions again and saves it. Built-in songs are read-only ("Save as my copy")."""

import copy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from riyaz import config, editor, songs
from riyaz.server import create_app

MIDI = Path(__file__).resolve().parent / "data" / "midi"


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        yield c


def user_song(client) -> dict:
    data = (MIDI / "la-native.mid").read_bytes()
    token = client.post("/api/import/midi?name=la-native.mid", content=data).json()["token"]
    sid = client.post(f"/api/import/midi/{token}/song", json={}).json()["song"]["id"]
    return client.get(f"/api/editor/{sid}").json()["song"]


def edit_payload(song: dict) -> dict:
    return {k: copy.deepcopy(song[k]) for k in ("title", "bpm", "key", "time_signature", "notes", "sections")} | {
        "loop": copy.deepcopy(song.get("loop"))}


def save(client, sid, payload, as_copy=False):
    return client.post("/api/editor/save", json={"song_id": sid, "song": payload, "copy": as_copy})


def test_editor_get_song(client):
    r = client.get("/api/editor/ode-to-joy").json()
    assert r["song"]["id"] == "ode-to-joy" and r["user_song"] is False
    assert "C major" in r["keys"] and "A minor" in r["keys"] and len(r["keys"]) == 24
    assert client.get("/api/editor/nope").status_code == 404


def test_move_delete_add_and_change_length(client):
    song = user_song(client)
    sid = song["id"]
    p = edit_payload(song)
    n0 = len(p["notes"])
    first = p["notes"][0]
    # move the first note (later by 1 click, 2 keys up), its finger must be given again
    first["start"] += 1.0
    first["pitch"] += 2
    first["finger"] = None
    moved = (first["pitch"], first["start"])
    # remove the last note
    p["notes"].pop()
    # add a note (no finger: the app gives one)
    p["notes"].append({"pitch": 72, "start": 2.5, "dur": 0.5, "hand": "R", "finger": None, "vel": 80})
    # change the length of the second note
    p["notes"][1]["dur"] = 2.0
    r = save(client, sid, p)
    assert r.status_code == 200, r.text
    saved = r.json()["song"]
    assert saved["id"] == sid and len(saved["notes"]) == n0
    by = {(n["pitch"], n["start"]): n for n in saved["notes"]}
    assert moved in by and by[moved]["finger"] in (1, 2, 3, 4, 5)
    assert (72, 2.5) in by and by[(72, 2.5)]["finger"] in (1, 2, 3, 4, 5)
    assert [n["id"] for n in saved["notes"]] == list(range(n0))
    assert songs.get(sid)["notes"] == saved["notes"]  # on disk
    assert r.json()["card"]["id"] == sid


def test_change_hand_and_finger_of_a_selection(client):
    song = user_song(client)
    p = edit_payload(song)
    right = [n for n in p["notes"] if n["hand"] == "R"][:4]
    # 4 right-hand notes to the left hand, with finger 2 (one note at each time).
    picked = []
    starts = set()
    for n in right:
        if n["start"] in starts:
            continue
        starts.add(n["start"])
        n["hand"] = "L"
        n["finger"] = 2
        picked.append((n["pitch"], n["start"]))
    # The left hand must not have 2 fingers 2 at one time: clear the fingers of other left-hand notes there.
    for n in p["notes"]:
        if n["hand"] == "L" and n["start"] in starts and (n["pitch"], n["start"]) not in picked:
            n["finger"] = None
    r = save(client, song["id"], p)
    assert r.status_code == 200, r.text
    by = {(n["pitch"], n["start"]): n for n in r.json()["song"]["notes"]}
    for k in picked:
        assert by[k]["hand"] == "L" and by[k]["finger"] == 2
    # The hand positions follow the fingers.
    for pos in r.json()["song"]["hand_positions"]:
        assert pos["hand"] in ("R", "L")


def test_parts_loop_speed_and_key(client):
    song = user_song(client)
    p = edit_payload(song)
    p["sections"] = [{"name": "Verse", "start": 0, "end": 12}, {"name": "", "start": 12, "end": song["end"]}]
    p["loop"] = {"start": 6, "end": 18}
    p["bpm"] = 120
    p["key"] = "G major"
    r = save(client, song["id"], p)
    assert r.status_code == 200, r.text
    s = r.json()["song"]
    # A6: an own part name stays; an empty name becomes "Part N".
    assert [x["name"] for x in s["sections"]] == ["Verse", "Part 2"] and s["sections"][1]["start"] == 12
    assert s["loop"] == {"start": 6.0, "end": 18.0}
    assert s["bpm"] == 120 and s["key"] == "G major"
    # The loop plays in practice as a repeated place.
    r = client.post("/api/practice/start", json={"song_id": s["id"], "mode": "wait", "hands": ["R", "L"],
                                                 "span": [s["loop"]["start"], s["loop"]["end"]]})
    assert r.status_code == 200 and r.json()["range"] == [6.0, 18.0]
    client.post("/api/practice/stop", json={})
    # Remove the loop.
    p["loop"] = None
    assert "loop" not in save(client, song["id"], p).json()["song"]


@pytest.mark.parametrize("change, text", [
    (lambda p: p.update(notes=[]), "The song has no notes. Add one or more notes."),
    (lambda p: p["notes"][0].update(pitch=30), "A note is not on the 61 keys of the keyboard. Move the note up or down."),
    (lambda p: p["notes"][0].update(start=-1), "A note starts before the start of the song. Move the note to the right."),
    (lambda p: p["notes"][0].update(dur=0), "A note is too short. Make the note longer."),
    (lambda p: p["notes"][0].update(hand="X"), "A note has no hand. Select the right hand or the left hand for the note."),
    (lambda p: p["notes"][0].update(finger=7), "A finger number must be 1 to 5."),
    (lambda p: p.update(bpm=500), "Set a speed from 20 to 300."),
    (lambda p: p.update(title="  "), "Give the song a name."),
    (lambda p: p.update(key="H major"), "Select a key for the song from the list."),
    (lambda p: p.update(loop={"start": 8, "end": 4}), "The loop ends before it starts. Set the loop again."),
    (lambda p: p.update(sections=[{"start": 0, "end": 8}, {"start": 4, "end": 12}]),
     "Two parts are at the same place. Set the parts again."),
    (lambda p: p["notes"].append(dict(p["notes"][0])), "Two notes on the same key start at the same time. Remove one of them."),
])
def test_validation_before_save(client, change, text):
    song = user_song(client)
    p = edit_payload(song)
    change(p)
    r = save(client, song["id"], p)
    assert r.status_code == 400 and r.json()["detail"] == text
    assert songs.get(song["id"])["notes"] == song["notes"]  # nothing saved


def test_finger_order_of_keys_together(client):
    song = songs.get("ode-to-joy")
    p = edit_payload(song)
    p["notes"] = [{"pitch": 60, "start": 0, "dur": 1, "hand": "R", "finger": 3, "vel": 80},
                  {"pitch": 64, "start": 0, "dur": 1, "hand": "R", "finger": 1, "vel": 80}]
    r = save(client, "ode-to-joy", p, as_copy=True)
    assert r.status_code == 400 and r.json()["detail"].startswith("The fingers of keys together are in the wrong order.")
    p["notes"][1]["finger"] = 3
    r = save(client, "ode-to-joy", p, as_copy=True)
    assert r.json()["detail"] == "Two keys together have the same finger. Change one of the fingers."


def test_built_in_song_is_read_only_and_save_as_my_copy(client):
    song = songs.get("ode-to-joy")
    before = copy.deepcopy(song["notes"])
    p = edit_payload(song)
    p["notes"][0]["pitch"] = 62
    r = save(client, "ode-to-joy", p)
    assert r.status_code == 400 and r.json()["detail"] == 'You cannot change a song of the app. Select "Save as my copy".'
    r = save(client, "ode-to-joy", p, as_copy=True)
    assert r.status_code == 200, r.text
    c = r.json()["song"]
    assert c["id"].startswith("my-ode-to-joy-my-copy-copy-") and c["title"] == "Ode to Joy (my copy)"
    assert c["copy_of"] == "ode-to-joy" and c["source"] == "copy" and c["notes"][0]["pitch"] == 62
    assert songs.get("ode-to-joy")["notes"] == before  # the built-in song did not change
    assert not (config.user_songs_path() / "ode-to-joy.json").exists()
    assert songs.is_user_song(c["id"]) and not songs.is_user_song("ode-to-joy")
    # The copy is a user song: it can be saved in place.
    p2 = edit_payload(c)
    p2["bpm"] = 70
    assert save(client, c["id"], p2).json()["song"]["bpm"] == 70
    # The card list has the copy.
    assert any(s["id"] == c["id"] for s in client.get("/api/songs").json()["songs"])


def test_editor_save_needs_own_origin(client):
    song = songs.get("ode-to-joy")
    r = client.post("/api/editor/save", json={"song_id": "ode-to-joy", "song": edit_payload(song), "copy": True},
                    headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_saved_song_plays_in_wait_mode(client):
    song = user_song(client)
    p = edit_payload(song)
    p["notes"] = p["notes"][:20]
    sid = save(client, song["id"], p).json()["song"]["id"]
    r = client.post("/api/practice/start", json={"song_id": sid, "mode": "wait", "hands": ["R", "L"]})
    assert r.status_code == 200
    client.post("/api/practice/stop", json={})


def test_check_function_numbers():
    with pytest.raises(editor.EditorError):
        editor.check({"title": "x", "bpm": True, "notes": []})
    out = editor.check({"title": "T", "bpm": 90, "notes": [{"pitch": 60, "start": 0, "dur": 1, "hand": "R"}]})
    assert out["notes"][0]["vel"] == 80 and out["time_signature"] == [4, 4]


# ------------------------------------------------------------------- Phase 5 review fixes (A4-A6)


def test_save_as_copy_does_not_write_over_an_edited_copy(client):
    song = songs.get("ode-to-joy")
    p = edit_payload(song)
    p["notes"][0]["pitch"] = 62
    first = save(client, "ode-to-joy", p, as_copy=True).json()["song"]
    again = save(client, "ode-to-joy", p, as_copy=True).json()["song"]
    assert again["id"] == first["id"]  # the same song: the same file
    p2 = edit_payload(first)
    p2["bpm"] = 70
    save(client, first["id"], p2)  # the user changes the copy
    third = save(client, "ode-to-joy", p, as_copy=True).json()["song"]
    assert third["id"] == f"{first['id']}-2"
    assert songs.get(first["id"])["bpm"] == 70


def test_same_key_in_two_hands_cannot_sound_at_once(client):
    """A5: the overlap check is for each key, in both hands. A note that sounds into the next
    note on the same key ends when that note starts."""
    base = {"title": "T", "bpm": 100, "key": "C major", "time_signature": [4, 4], "sections": []}
    notes = [{"pitch": 60, "start": 0.0, "dur": 2.0, "hand": "R", "finger": 1},
             {"pitch": 60, "start": 1.0, "dur": 1.0, "hand": "L", "finger": 1}]
    out = editor.check({**base, "notes": notes})
    assert [(n["start"], n["dur"]) for n in out["notes"] if n["pitch"] == 60] == [(0.0, 1.0), (1.0, 1.0)]
    notes[1]["start"] = 0.02
    with pytest.raises(editor.EditorError, match="Two notes on the same key sound at the same time"):
        editor.check({**base, "notes": notes})
