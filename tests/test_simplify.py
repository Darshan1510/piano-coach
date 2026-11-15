"""Phase 5a: song simplifier (PLAN 11.2) and easy versions by level (PLAN 8.4). No CoreMIDI."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from riyaz import config, course, difficulty, simplify, songs, theory
from riyaz.importers import midi_import
from riyaz.practice import Practice
from riyaz.server import create_app
from tools.fake_player import play_plan, timed_events

MIDI = Path(__file__).resolve().parent / "data" / "midi"
TWO_HAND = ["bach-minuet-a-minor-bwv-anh-120.mid", "la-native.mid"]


def imported(name: str) -> dict:
    return midi_import.build_song(midi_import.parse((MIDI / name).read_bytes(), name))


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def play_along(song, hands):
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    st = p.start(song, mode="play", hands=hands, count_in=True, accompany=False)
    plan = play_plan(song, hands, start=st["range"][0], end=st["range"][1])
    keys = timed_events(plan, lambda b: st["anchor_t"] + (b - st["anchor_beat"]) / st["rate"])
    end_t = st["anchor_t"] + (st["range"][1] - st["anchor_beat"]) / st["rate"] + 1.0
    i = 0
    while clk.t < end_t and not p.state()["done"]:
        while i < len(keys) and keys[i][0] <= clk.t:
            t, on, pitch, vel = keys[i]
            p.on_midi({"type": "note_on" if on else "note_off", "pitch": pitch, "velocity": vel, "t": t})
            i += 1
        p.tick(clk.t)
        clk.t += 0.005
    return [e for e in events if e["type"] == "practice_end"]


def wait_mode(song, hands):
    """A fake player that presses each expected key when the song waits (as test_practice)."""
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    p.start(song, mode="wait", hands=hands, count_in=True, speed=1.5)
    for _ in range(200000):
        clk.t += 0.01
        p.tick()
        st = p.state()
        if st["done"]:
            break
        if st["waiting"]:
            for e in st["expected"]:
                p.on_midi({"type": "note_on", "pitch": e["pitch"], "velocity": 80, "t": clk.t})
            for e in st["expected"]:
                p.on_midi({"type": "note_off", "pitch": e["pitch"], "velocity": 0, "t": clk.t})
    return [e for e in events if e["type"] == "practice_end"]


# ----------------------------------------------------------------------------- helpers


def test_chord_names_and_keys():
    assert simplify.parse_chord("Am7") == (9, "m")
    assert simplify.parse_chord("Bb") == (10, "")
    assert simplify.parse_chord("F#dim") == (6, "dim")
    assert simplify.parse_chord("Emaj7") == (4, "")
    assert simplify.parse_chord("Dsus4") == (2, "")
    assert simplify.parse_chord("H") is None
    assert simplify.parse_key("Bb major") == (10, "major")
    assert simplify.parse_key("A minor") == (9, "minor")
    assert simplify.transpose_shift((2, "major"), "C") == -2  # D -> C
    assert simplify.transpose_shift((7, "major"), "C") == 5  # G -> C (up 5, nearer than down 7? -7 is out of -6..5)
    assert simplify.transpose_shift((4, "minor"), "C") == 5  # E minor -> A minor
    assert simplify.transpose_shift((9, "minor"), "G") == -5  # A minor -> E minor


def test_skyline_takes_the_highest_note_and_drops_very_short_notes():
    notes = [
        {"id": 0, "pitch": 60, "start": 0.0, "dur": 1.0, "hand": "R", "finger": 1, "vel": 80},
        {"id": 1, "pitch": 67, "start": 0.0, "dur": 1.0, "hand": "R", "finger": 5, "vel": 80},
        {"id": 2, "pitch": 65, "start": 1.0, "dur": 0.1, "hand": "R", "finger": 4, "vel": 80},  # very short
        {"id": 3, "pitch": 64, "start": 1.1, "dur": 0.9, "hand": "R", "finger": 3, "vel": 80},
        {"id": 4, "pitch": 48, "start": 0.0, "dur": 2.0, "hand": "L", "finger": 5, "vel": 80},  # left hand: not melody
    ]
    song = songs.validate({"id": "t", "title": "T", "bpm": 100, "notes": notes})
    mel = simplify.skyline(song)
    assert [(n["pitch"], n["start"]) for n in mel] == [(67, 0.0), (64, 1.1)]
    assert mel[0]["dur"] == pytest.approx(1.1)  # the note before gets the time of the short note


def test_thin_removes_fast_notes_and_keeps_strong_times():
    mel = [{"pitch": 60 + i, "start": i * 0.25, "dur": 0.25, "hand": "R", "vel": 80} for i in range(8)]
    out = simplify.thin(mel, 120.0, 4, 0.3)  # 0.25 beat at 120 = 0.125 s: too fast
    starts = [n["start"] for n in out]
    assert all(b - a >= 0.6 - 1e-6 for a, b in zip(starts, starts[1:]))  # 0.3 s = 0.6 beat
    assert 0.0 in starts and 1.0 in starts  # the clicks stay


# ------------------------------------------------------------------------- versions by level


@pytest.mark.parametrize("name", TWO_HAND)
def test_level_5_version_is_melody_and_block_chords(name):
    src = imported(name)
    assert src["level"] > 5
    v = simplify.for_level(src, 5)
    assert v is not None and v["level"] <= 5, v["difficulty"]
    assert v["version_of"]["id"] == src["id"] and v["version_of"]["level"] == 5 and v["source"] == "simplified"
    right = [n for n in v["notes"] if n["hand"] == "R"]
    left = [n for n in v["notes"] if n["hand"] == "L"]
    # Melody: one key at a time, at middle C or higher.
    starts = [n["start"] for n in right]
    assert len(starts) == len(set(starts)) and min(n["pitch"] for n in right) >= 60
    # Left hand: 3 keys together (a triad in root position) below middle C.
    groups = {}
    for n in left:
        groups.setdefault(n["start"], []).append(n["pitch"])
    assert groups and all(len(g) == 3 for g in groups.values())
    for g in groups.values():
        g.sort()
        assert g[2] - g[0] in (6, 7, 8) and g[2] < 60
        assert theory.detect_chord(g) is not None
    assert "keys_together" in v["difficulty"]["skills"]
    assert "thumb_under" not in v["difficulty"]["skills"] and "fast_runs" not in v["difficulty"]["skills"]
    # Every note has a finger, the chords are named, and the parts are kept.
    assert all(n["finger"] in (1, 2, 3, 4, 5) for n in v["notes"])
    assert v["chords"] and v["sections"] == src["sections"]


@pytest.mark.parametrize("name", TWO_HAND)
def test_level_5_version_plays_in_wait_mode_and_play_along(name):
    """Acceptance 1 (fake clock): the fake player completes the Level-5 version in wait mode and
    scores >= 98 in play-along (exact timing)."""
    v = simplify.for_level(imported(name), 5)
    end = wait_mode(v, ["R", "L"])
    assert end and end[0]["completed"] and end[0]["wrong"] == 0
    assert end[0]["stops"] == len({n["start"] for n in v["notes"]})
    end = play_along(v, ["R", "L"])
    assert end and end[0]["score"]["total"] >= 98, end[0]["score"]


@pytest.mark.parametrize("name", TWO_HAND + ["les-graces-one-track.mid"])
def test_level_1_version_is_a_five_finger_melody_in_c(name):
    v = simplify.for_level(imported(name), 1)
    assert v["level"] == 1, v["difficulty"]
    assert {n["hand"] for n in v["notes"]} == {"R"}
    assert not any(theory.is_black(n["pitch"]) for n in v["notes"])
    assert v["difficulty"]["stats"]["hand_moves"] == 0
    assert v["difficulty"]["skills"] == ["right_hand"]
    assert v["version_of"]["fingering"] == {"R": "beginner"}
    assert v["key"] in ("C major", "A minor")


def test_level_3_version_adds_left_hand_single_keys():
    v = simplify.for_level(imported("la-native.mid"), 3)
    assert v["level"] <= 3
    left = [n for n in v["notes"] if n["hand"] == "L"]
    assert left and len({n["start"] for n in left}) == len(left)  # one key at a time
    assert max(n["pitch"] for n in left) < 60


def test_no_version_when_the_song_fits():
    ode = songs.get("ode-to-joy")
    assert simplify.for_level(ode, 3) is None


def test_options_melody_only_roots_transpose_and_slow():
    src = imported("la-native.mid")  # D major, 182
    only = simplify.make_version(src, left="none", key="same")
    assert {n["hand"] for n in only["notes"]} == {"R"} and only["key"] == "D major"
    roots = simplify.make_version(src, left="roots", key="C", slow=True)
    assert roots["key"] == "C major" and roots["bpm"] == pytest.approx(182 * 0.75, abs=0.01)
    left = [n for n in roots["notes"] if n["hand"] == "L"]
    assert left and all(48 <= n["pitch"] <= 59 for n in left)
    # Moving the song to C gives fewer black keys than the original.
    black = lambda s: sum(theory.is_black(n["pitch"]) for n in s["notes"])  # noqa: E731
    assert black(simplify.make_version(src, left="chords", key="C")) < black(simplify.make_version(src, left="chords"))
    half = simplify.make_version(src, left="chords", change="half")
    bar = simplify.make_version(src, left="chords", change="bar")
    assert len(half["notes"]) > len(bar["notes"])
    g = simplify.make_version(src, left="none", key="G")
    assert g["key"] == "G major"
    with pytest.raises(simplify.SimplifyError):
        simplify.make_version(src, left="all")


def test_one_track_song_and_built_in_song_versions():
    v = simplify.make_version(songs.get("frere-jacques-both-hands"), left="chords")
    assert v["id"].startswith("my-frere-jacques-both-hands-easy-") and len(v["id"]) <= 64
    v = simplify.for_level(imported("les-graces-one-track.mid"), 5)
    assert v["level"] <= 5


# ----------------------------------------------------------------------- saving and the cards


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        c.riyaz = app.state.riyaz
        yield c


def import_via(client, name):
    data = (MIDI / name).read_bytes()
    token = client.post(f"/api/import/midi?name={name}", content=data).json()["token"]
    return client.post(f"/api/import/midi/{token}/song", json={}).json()


def test_simplify_route_saves_a_linked_song(client):
    r = import_via(client, "bach-minuet-a-minor-bwv-anh-120.mid")
    src = r["song"]
    out = client.post(f"/api/songs/{src['id']}/simplify", json={"left": "chords", "key": "C", "slow": True})
    assert out.status_code == 200, out.text
    v = out.json()["song"]
    assert v["version_of"]["id"] == src["id"] and v["source"] == "simplified"
    full = client.get(f"/api/songs/{v['id']}").json()
    assert full["version_of"]["options"] == {"left": "chords", "key": "C", "slow": True, "change": "bar"}
    assert (config.user_songs_path() / f"{v['id']}.json").is_file()
    # The original song does not change.
    assert client.get(f"/api/songs/{src['id']}").json()["notes"] == songs.get(src["id"])["notes"]
    # For the user's level.
    lv = client.post(f"/api/songs/{src['id']}/simplify", json={"for_level": True}).json()
    assert lv["fits"] and lv["song"]["level"] <= 1
    bad = client.post(f"/api/songs/{src['id']}/simplify", json={"left": "x"})
    assert bad.status_code == 400 and bad.json()["detail"] == "Select what the left hand plays."
    assert client.post("/api/songs/nope/simplify", json={}).status_code == 404
    assert client.post("/api/songs/ode-to-joy/simplify", json={"for_level": True}).status_code == 400
    assert client.post(f"/api/songs/{src['id']}/simplify", json={}, headers={"Origin": "http://evil.example"}).status_code == 403


def test_card_says_easy_version_and_level_up_makes_a_new_version(client):
    r = import_via(client, "la-native.mid")
    src_id = r["song"]["id"]
    assert r["easy"]["version_of"]["level"] == 1
    cards = {s["id"]: s for s in client.get("/api/songs").json()["songs"]}
    assert cards[src_id]["difficulty"]["text"] == "You can play the easy version now."
    assert cards[src_id]["easy"]["id"] == r["easy"]["id"]
    # Level up: finish the 3 Level 1 songs (wait mode is enough at Level 1).
    events = []
    hub = client.app.state.hub
    orig = hub.publish
    hub.publish = lambda e: (events.append(e), orig(e))
    try:
        c = client.riyaz["course"]
        assert c.user_level() == 1
        from riyaz import server  # noqa: F401
        for sid in ("mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle"):
            song = songs.get(sid)
            run = {"type": "practice_end", "song_id": sid, "mode": "wait", "hands": ["R"], "section": None,
                   "speed": 1.0, "completed": True, "accuracy": 100.0, "stops": 10, "wrong": 0, "errors": [],
                   "range": [0, song["end"]], "run": 1}
            client.riyaz["practice"].sink(run)
        client.riyaz["flush_results"]()
    finally:
        hub.publish = orig
    ups = [e for e in events if e.get("type") == "course" and e.get("level_up")]
    assert ups, [e.get("level") for e in events if e.get("type") == "course"]
    nv = ups[0]["new_versions"]
    assert len(nv) == 1 and nv[0]["source_id"] == src_id
    assert nv[0]["text"] == "Your song 'La native' has a new version for your level."
    v = songs.get(nv[0]["id"])
    assert v["version_of"]["level"] == 2 and v["level"] <= 2


def test_needs_version_rules():
    assert not simplify.needs_version(songs.get("ode-to-joy"), 1)
    src = imported("la-native.mid")
    assert simplify.needs_version(src, 3)
    assert not simplify.needs_version(simplify.for_level(src, 3), 1)  # a version never gets a version
    assert difficulty.SKILLS["keys_together"][0] == simplify.CHORD_LEVEL == 5
    assert course is not None


# ------------------------------------------------------------------- Phase 5 review fixes (A1-A4)


def shared_keys(song: dict) -> list[tuple]:
    """Pairs of a right-hand and a left-hand note on the same key that sound at the same time."""
    right = [n for n in song["notes"] if n["hand"] == "R"]
    left = [n for n in song["notes"] if n["hand"] == "L"]
    return [(r["pitch"], r["start"], l["start"]) for r in right for l in left
            if r["pitch"] == l["pitch"] and r["start"] < l["start"] + l["dur"] - 1e-6
            and l["start"] < r["start"] + r["dur"] - 1e-6]


def audio_like(src: dict) -> dict:
    """A song as the audio import makes it, from the notes of a song (a fake worker result)."""
    from riyaz.importers import audio_import

    spb = 60.0 / src["bpm"]
    result = {"notes": [[n["start"] * spb, (n["start"] + n["dur"]) * spb, n["pitch"], 80] for n in src["notes"]],
              "bpm": src["bpm"], "beats": [i * spb for i in range(int(src["end"]) + 1)],
              "duration": src["end"] * spb, "seconds": 1.0, "backend": "test"}
    song, _midi = audio_import.build_song(result, "fake.mp3", 1)
    return song


def _sources():
    out = [imported(p.name) for p in sorted(MIDI.glob("*.mid"))]
    out += [imported(f"synthetic/{p.name}") for p in sorted((MIDI / "synthetic").glob("*.mid"))
            if p.name not in ("drums.mid", "empty-tracks.mid")]
    out += [s for s in songs.load_all().values() if len(songs.hands_of(s)) == 2]
    out += [audio_like(imported(n)) for n in TWO_HAND]
    return out


def test_no_key_in_both_hands_at_the_same_time():
    """A1: at Level 3 the 2 hand positions can both have middle C. No version has a key in
    both hands at the same time (the editor check would refuse the song)."""
    from riyaz import editor

    count = 0
    for src in _sources():
        for level in range(1, 9):
            try:
                v = simplify.for_level(src, level) or simplify.make_version(src, left="chords", level=level)
            except simplify.SimplifyError:
                continue
            assert not shared_keys(v), (src["id"], level, shared_keys(v)[:3])
            editor.check(v)  # the editor accepts the version
            count += 1
        for left in ("roots", "chords"):
            v = simplify.make_version(src, left=left, key="C")
            assert not shared_keys(v), (src["id"], left)
    assert count > 60


def test_level_3_hand_positions_do_not_share_keys():
    src = imported("bach-minuet-a-minor-bwv-anh-120.mid")
    v = simplify.for_level(src, 3)
    right = {n["pitch"] for n in v["notes"] if n["hand"] == "R"}
    left = {n["pitch"] for n in v["notes"] if n["hand"] == "L"}
    assert left and max(left) < min(right)


def test_skyline_keeps_a_held_melody_note_over_an_inner_voice():
    """A2: G5 held for 2 beats while an inner voice moves under it: the melody is G5 (2 beats),
    not G5 cut by the inner voice."""
    notes = [
        {"id": 0, "pitch": 79, "start": 0.0, "dur": 2.0, "hand": "R", "finger": 5, "vel": 80},
        {"id": 1, "pitch": 72, "start": 0.0, "dur": 1.0, "hand": "R", "finger": 1, "vel": 80},
        {"id": 2, "pitch": 74, "start": 1.0, "dur": 1.0, "hand": "R", "finger": 2, "vel": 80},
        {"id": 3, "pitch": 77, "start": 2.0, "dur": 1.0, "hand": "R", "finger": 4, "vel": 80},
        {"id": 4, "pitch": 76, "start": 3.0, "dur": 1.0, "hand": "R", "finger": 3, "vel": 80},
    ]
    song = songs.validate({"id": "t", "title": "T", "bpm": 100, "notes": notes})
    mel = simplify.skyline(song)
    assert [(n["pitch"], n["start"], n["dur"]) for n in mel] == [(79, 0.0, 2.0), (77, 2.0, 1.0), (76, 3.0, 1.0)]


def _tune(pitches, hand_l=True):
    notes = [{"id": i, "pitch": p, "start": float(i), "dur": 1.0, "hand": "R", "finger": None, "vel": 80}
             for i, p in enumerate(pitches)]
    if hand_l:  # a hard left hand, so that the song is above Level 1
        notes += [{"id": 100 + i, "pitch": 36 + (i * 7) % 12, "start": i * 0.5, "dur": 0.5, "hand": "L",
                   "finger": None, "vel": 80} for i in range(len(pitches) * 2)]
    return songs.validate({"id": "tune", "title": "Tune", "bpm": 100, "key": "C major", "notes": notes})


def test_a_tune_that_fits_one_position_does_not_change():
    """A3: a tune in one 5-finger position keeps every note (no note gets another name)."""
    tune = [60, 62, 64, 65, 67, 65, 64, 62, 60, 64, 67, 64, 60]
    v = simplify.make_version(_tune(tune), level=1)
    assert [n["pitch"] for n in v["notes"] if n["hand"] == "R"] == tune
    assert v["version_of"]["changed"] == 0 and simplify.changed_text(v["version_of"]) == ""


def test_changed_notes_are_counted_and_the_card_says_so():
    """A3: notes out of the position get another name; the version counts them and the card
    has the text."""
    tune = [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60]  # C to C and back
    v = simplify.make_version(_tune(tune), key="same", level=1)
    got = [n["pitch"] for n in v["notes"] if n["hand"] == "R"]
    want_changed = sum(1 for a, b in zip(tune, got) if a % 12 != b % 12)
    assert v["version_of"]["changed"] == want_changed and want_changed >= 3
    card = songs.summary(v, 1)
    assert card["version_of"]["changed_text"] == simplify.CHANGED_TEXT
    assert simplify.CHANGED_TEXT == "Some notes are different, so that one hand position plays the song."


def test_a_new_version_does_not_write_over_an_edited_version(client):
    """A4: the same version again keeps its id; after an edit, a new version gets a new id and
    the edit stays."""
    src = import_via(client, "bach-minuet-a-minor-bwv-anh-120.mid")["song"]
    opts = {"left": "roots", "key": "C"}
    a = client.post(f"/api/songs/{src['id']}/simplify", json=opts).json()["song"]
    b = client.post(f"/api/songs/{src['id']}/simplify", json=opts).json()["song"]
    assert a["id"] == b["id"]  # the same song: no new file
    full = client.get(f"/api/editor/{a['id']}").json()["song"]
    payload = {k: full[k] for k in ("title", "bpm", "key", "time_signature", "notes", "sections")}
    payload["notes"] = [dict(n) for n in full["notes"]][1:]  # the user removes the first note
    assert client.post("/api/editor/save", json={"song_id": a["id"], "song": payload}).status_code == 200
    c = client.post(f"/api/songs/{src['id']}/simplify", json=opts).json()["song"]
    assert c["id"] == f"{a['id']}-2"
    assert len(songs.get(a["id"])["notes"]) == len(full["notes"]) - 1  # the edit stays
    assert len(songs.get(c["id"])["notes"]) == len(full["notes"])
