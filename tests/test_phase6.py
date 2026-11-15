"""Phase 6: lead-sheet mode, transpose trainer, dynamics coaching, the foot switch (CC 64) with
the "no pedal ever" path, the free-play recorder (MIDI export round trip), the weekly coach (rule
summary, Ollama client with a fake local server and with no server), course Levels 9-10.
Fake clock, no CoreMIDI (the real-port runs are in tests/test_midi_virtual.py and PROGRESS.md)."""

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import mido
import pytest
from fastapi.testclient import TestClient

from riyaz import coach, config, course, dynamics, leadsheet, recorder as recorder_mod, songs, transpose
from riyaz.drill import Drill
from riyaz.importers import midi_import
from riyaz.practice import Practice, PracticeError
from riyaz.server import create_app
from tests.test_play import Clock, of
from tools.fake_player import lead_left_events, play_plan, timed_events

OWN = {"Origin": "http://127.0.0.1:8020"}
EVIL = {"Origin": "http://evil.example"}


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        c.riyaz = app.state.riyaz
        c.hub = app.state.hub
        yield c


def drive(song, hands=("R",), lead=False, left=True, wrong=False, vel=None, speed=1.0):
    """A play-along run with a fake clock. Lead: the tune + an own left hand (fake_player)."""
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    st = p.start(song, mode="play", hands=list(hands), speed=speed, count_in=True, accompany=False, lead=lead)
    plan = play_plan(song, ["R"] if lead else hands, start=st["range"][0], end=st["range"][1], vel=vel)
    if lead and left:
        plan["events"] += lead_left_events(leadsheet.sheet(song), *st["range"], wrong=wrong)
    at, ab, rate = st["anchor_t"], st["anchor_beat"], st["rate"]
    keys = timed_events(plan, lambda b: at + (b - ab) / rate)
    end_t = at + (st["range"][1] - ab) / rate + 1.0
    i = 0
    while clk.t < end_t and not p.state()["done"]:
        while i < len(keys) and keys[i][0] <= clk.t:
            t, on, pitch, v = keys[i]
            # The MIDI service names the velocity "vel" (riyaz/midi_io.py).
            p.on_midi({"type": "note_on" if on else "note_off", "pitch": pitch, "vel": v, "t": t})
            i += 1
        p.tick(clk.t)
        clk.t += 0.005
    return p, events


# ---------------------------------------------------------------------- lead sheet


def test_chord_tones_and_names():
    assert leadsheet.chord_tones("C") == {0, 4, 7}
    assert leadsheet.chord_tones("Am") == {9, 0, 4}
    assert leadsheet.chord_tones("G7") == {7, 11, 2, 5}
    assert leadsheet.chord_tones("F/C") == {5, 9, 0}
    assert leadsheet.chord_tones("Bb") == {10, 2, 5} and leadsheet.chord_tones("F#m") == {6, 9, 1}
    assert leadsheet.chord_tones("Xyz") == frozenset() and leadsheet.parse("C/E") == (0, "", 4)


def test_chords_of_song_field_or_left_hand():
    hb = songs.get("happy-birthday")
    assert [c["name"] for c in leadsheet.chords_of(hb)] == ["C", "G", "G", "C", "C", "F", "C", "G", "C"]
    # No chords field: names from the left-hand notes (one for each group of clicks).
    pop = songs.get("pop-loop")
    assert not pop["chords"]
    names = [c["name"] for c in leadsheet.chords_of(pop)]
    assert names[:4] == ["C", "G", "Am", "F"] and "Em" in names
    assert leadsheet.melody_split(hb) == min(n["pitch"] for n in hb["notes"] if n["hand"] == "R")


def test_lead_scorer_rules():
    chords = [{"start": 0, "dur": 4, "name": "C"}, {"start": 4, "dur": 4, "name": "G"}]
    s = leadsheet.LeadScorer(chords, 60, 0, 8)
    assert s.is_left(55) and not s.is_left(60)
    assert s.press(48, 0.0, 1.0)["ok"]
    assert not s.press(50, 1.0, 1.0)["ok"]  # D is not in C
    r = s.press(55, 3.9, 1.0)  # 100 ms before G: counts for G (and G is in C too)
    assert r["ok"]
    r = s.press(47, 3.9, 1.0)  # B: not in C, in the next chord G (inside the window)
    assert r["ok"] and r["chord"] == "G"
    out = s.finish()
    # C: right C, G + wrong D -> covered (root), credit (2 - 1) / 2. G: only B (the third) -> not covered.
    assert out["covered"] == 1 and out["chords"] == 2 and out["keys"] == 4 and out["tone_pct"] == 75.0
    assert out["score"] == 25
    empty = leadsheet.LeadScorer(chords, 60, 0, 8).finish()
    assert empty["score"] == 0 and empty["cover_pct"] == 0
    assert leadsheet.combined(100, 0) == 60 and leadsheet.combined(100, 100) == 100
    # Below LEAD_LEFT_PASS the total stays below the song-done score.
    assert leadsheet.combined(100, 69) == config.SONG_DONE_SCORE - 1 and leadsheet.combined(100, 70) == 88
    assert leadsheet.combined(93, None) == 93


def _left(song, plan):
    """The left-hand score of `plan(sc, chord)` (keys for each chord span) over the whole song."""
    sh = leadsheet.sheet(song)
    sc = leadsheet.LeadScorer(sh["chords"], sh["split"], 0, song["end"])
    plan(sc, sh)
    return sc.finish()["score"]


def _every(song, keys, step=0.5):
    def plan(sc, sh):
        b, k = 0.0, 0
        while b < song["end"]:
            sc.press(keys[k % len(keys)], b, 1.0)
            b, k = b + step, k + 1
    return plan


@pytest.mark.parametrize("sid", ["happy-birthday", "clementine", "pop-loop"])
def test_lead_score_cannot_be_gamed(sid):
    import itertools
    song = songs.get(sid)
    # One key (or 2 keys) played again and again for the whole song: no pass.
    best1 = max(_left(song, _every(song, [36 + pc])) for pc in range(12))
    best2 = max(_left(song, _every(song, [36 + a, 36 + b])) for a, b in itertools.combinations(range(12), 2))
    assert best1 < leadsheet.LEAD_LEFT_PASS and best2 < leadsheet.LEAD_LEFT_PASS
    assert leadsheet.combined(100, best1) < config.SONG_DONE_SCORE
    assert leadsheet.combined(100, best2) < config.SONG_DONE_SCORE

    def white(sc, sh):  # all white keys on every beat
        b = 0.0
        while b < song["end"]:
            for p in (36, 38, 40, 41, 43, 45, 47):
                sc.press(p, b, 1.0)
            b += 1

    def cluster(sc, sh):  # all 12 keys at each name
        for c in sh["chords"]:
            for p in range(36, 48):
                sc.press(p, c["start"], 1.0)

    assert _left(song, white) == 0 and _left(song, cluster) == 0
    assert leadsheet.combined(100, 0) < config.SONG_DONE_SCORE


@pytest.mark.parametrize("sid", ["happy-birthday", "clementine", "pop-loop"])
@pytest.mark.parametrize("kind", ["root", "root_fifth", "full", "inversion", "broken", "repeat"])
def test_lead_honest_patterns_score_high(sid, kind):
    song = songs.get(sid)

    def plan(sc, sh):
        for c in sh["chords"]:
            root, suffix, _ = leadsheet.parse(c["name"])
            shape, lo = leadsheet.SHAPES[suffix], 36 + root
            keys = {"root": [lo], "root_fifth": [lo, lo + 7], "full": [lo + i for i in shape[:3]],
                    "inversion": [lo + shape[1], lo + shape[2], lo + 12],
                    "broken": [lo, lo + shape[2], lo + shape[1], lo + shape[2]],
                    "repeat": [lo, lo, lo, lo]}[kind]
            for j, k in enumerate(keys):
                sc.press(k, c["start"] + j * c["dur"] / len(keys), 1.0)

    assert _left(song, plan) == 100


def test_lead_range_without_names_scores_the_tune_alone():
    song = dict(songs.get("happy-birthday"))
    song["chords"] = [{"start": 0, "dur": 3, "name": "C"}]  # names only at the start
    sc = leadsheet.LeadScorer(leadsheet.chords_of(song), 60, 6, 12)
    sc.press(48, 7, 1.0)
    out = sc.finish()
    assert out["chords"] == 0 and out["score"] is None
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    st = p.start(song, mode="play", span=[6.0, 12.0], count_in=True, accompany=False, lead=True)
    plan = play_plan(song, ["R"], start=st["range"][0], end=st["range"][1])
    at, ab, rate = st["anchor_t"], st["anchor_beat"], st["rate"]
    keys = timed_events(plan, lambda b: at + (b - ab) / rate)
    end_t = at + (st["range"][1] - ab) / rate + 1.0
    i = 0
    while clk.t < end_t and not p.state()["done"]:
        while i < len(keys) and keys[i][0] <= clk.t:
            t, on, pitch, v = keys[i]
            p.on_midi({"type": "note_on" if on else "note_off", "pitch": pitch, "vel": v, "t": t})
            i += 1
        p.tick(clk.t)
        clk.t += 0.005
    end = of(events, "practice_end")[0]
    assert end["lead"]["score"] is None and end["score"]["total"] == end["score"]["tune_total"] >= 98


@pytest.mark.parametrize("sid", ["happy-birthday", "clementine", "pop-loop"])
def test_lead_run_scores_the_left_hand_on_chord_tones(sid):
    song = songs.get(sid)
    _, ev = drive(song, lead=True)
    end = of(ev, "practice_end")[0]
    assert end["lead"]["score"] == 100 and end["score"]["total"] >= 98 and end["score"]["tune_total"] >= 98
    assert end["hands"] == ["R"]
    leads = of(ev, "practice_lead")
    assert leads and all(e["ok"] for e in leads)
    # No left hand: the tune alone is not enough for "done" (60 < 80).
    _, ev = drive(song, lead=True, left=False)
    end = of(ev, "practice_end")[0]
    assert end["lead"]["score"] == 0 and end["score"]["total"] <= 60
    # Wrong keys (a half step up, not keys of the name): low left-hand score.
    _, ev = drive(song, lead=True, wrong=True)
    assert of(ev, "practice_end")[0]["lead"]["score"] <= 10


def test_lead_needs_play_along_and_names():
    p = Practice(lambda e: None, now=Clock(), threaded=False)
    with pytest.raises(PracticeError):
        p.start(songs.get("happy-birthday"), mode="wait", lead=True)
    with pytest.raises(PracticeError):  # Level 1 songs: right hand only, no names
        p.start(songs.get("mary-had-a-little-lamb"), mode="play", lead=True)
    st = p.start(songs.get("happy-birthday"), mode="play", hands=["R", "L"], lead=True)
    assert st["lead"] and st["hands"] == ["R"] and not st["accompany"] and not st["loop"]


def test_lead_api_and_course_task(client):
    c = client
    sheet = c.get("/api/songs/happy-birthday/lead").json()
    assert sheet["chords"][0]["name"] == "C" and sheet["split"] == 67
    assert c.get("/api/songs/mary-had-a-little-lamb/lead").status_code == 400
    m = c.get("/api/course/moments/happy-birthday?task=lead").json()["moments"]
    assert [x["id"] for x in m] == ["lead_sheet"]
    assert all(x["id"] != "lead_sheet" for x in c.get("/api/course/moments/happy-birthday").json()["moments"])
    r = c.post("/api/practice/start", json={"song_id": "happy-birthday", "mode": "play", "lead": True}, headers=OWN).json()
    assert r["lead"] and r["hands"] == ["R"]
    assert c.post("/api/practice/start", json={"song_id": "happy-birthday", "lead": True}, headers=EVIL).status_code == 403


# ---------------------------------------------------------------------- transpose


def test_transpose_choices_and_song():
    src = songs.get("when-the-saints")  # F major
    ch = transpose.choices(src)
    assert ch and all(c["shift"] != 0 for c in ch) and ch[0]["black_keys"] == 0
    assert {"C major", "G major"} <= {c["key"] for c in ch[:2]}  # both have no black key in this tune
    blacks = [c["black_keys"] for c in ch]
    assert blacks == sorted(blacks)
    v = transpose.make(src, -5)
    assert v["key"] == "C major" and v["id"] == "my-when-the-saints-in-c-major"
    assert v["title"] == f"{src['title']} (in C)"
    assert v["version_of"]["kind"] == "transpose" and v["version_of"]["id"] == "when-the-saints"
    shift = v["version_of"]["shift"]
    assert shift % 12 == 7  # F -> C is down 5 or up 7
    a = sorted((n["start"], n["pitch"]) for n in src["notes"])
    b = sorted((n["start"], n["pitch"]) for n in v["notes"])
    assert [(t, p + shift) for t, p in a] == b
    assert all(config.KEY_LOW <= n["pitch"] <= config.KEY_HIGH and n["finger"] in (1, 2, 3, 4, 5) for n in v["notes"])
    hb = transpose.make(songs.get("happy-birthday"), -5)  # C -> G
    assert [c["name"] for c in hb["chords"]][:3] == ["G", "D", "D"] and hb["key"] == "G major"
    assert transpose.chord_name_after("F/C", 2) == "G/D" and transpose.chord_name_after("Am", 3) == "Cm"
    with pytest.raises(transpose.TransposeError):
        transpose.make(src, 0)
    with pytest.raises(transpose.TransposeError):
        transpose.make(src, 9)


def test_transposed_song_plays_and_finishes_the_task(client):
    c = client
    info = c.get("/api/songs/when-the-saints/keys").json()
    assert info["key"] == "F (happy sound)" and info["choices"] and info["versions"] == []
    assert c.post("/api/songs/when-the-saints/transpose", json={"shift": -5}, headers=EVIL).status_code == 403
    r = c.post("/api/songs/when-the-saints/transpose", json={"shift": -5}, headers=OWN).json()
    vid = r["song"]["id"]
    assert r["key"] == "C (happy sound)" and (config.user_songs_path() / f"{vid}.json").is_file()
    assert c.get(f"/api/songs/{vid}/keys").json()["versions"][0]["id"] == vid
    assert [m["id"] for m in c.get(f"/api/course/moments/{vid}").json()["moments"]] == ["new_key"]
    v = songs.get(vid)
    _, ev = drive(v, hands=("R", "L"))
    end = of(ev, "practice_end")[0]
    assert end["score"]["total"] >= 98
    res = c.riyaz["course"].record_run(end)
    assert res["task"] == "transpose" and res["key"] == "when-the-saints#transpose" and res["done"]
    assert "when-the-saints#transpose" in c.riyaz["course"].songs_done()
    assert "when-the-saints" not in c.riyaz["course"].songs_done()  # the F major song is its own row


def test_rule6_key_names_in_dynamic_text(client):
    """PLAN 7.4 Rule 6: with "major" locked (also after "skip to Level 10"), no dynamic text
    (key choices, the key now, a transposed title, the song cards) shows "major" or "minor"."""
    c = client
    c.post("/api/course/skip", json={"level": 10}, headers=OWN)
    assert "major_minor" not in c.riyaz["store"].terms()
    word = re.compile(r"\b(major|minor)\b", re.I)
    for sid in ("when-the-saints", "happy-birthday"):
        info = c.get(f"/api/songs/{sid}/keys").json()
        shown = [info["key"], info["title"]] + [x["key"] for x in info["choices"]]
        assert not any(word.search(t) for t in shown), shown
        assert all("happy sound" in x["key"] or "sad sound" in x["key"] for x in info["choices"])
        r = c.post(f"/api/songs/{sid}/transpose", json={"shift": info["choices"][0]["shift"]}, headers=OWN).json()
        assert not word.search(r["key"]) and not word.search(r["song"]["title"]), r
    cards = c.get("/api/songs").json()
    cards = cards.get("songs", cards) if isinstance(cards, dict) else cards
    assert not any(word.search(s["title"]) for s in cards)
    # A sad-sound key and the unlocked words.
    assert transpose.key_text("A minor", set()) == "A (sad sound)"
    c.riyaz["store"].unlock_term("major_minor")
    assert c.get("/api/songs/when-the-saints/keys").json()["key"] == "F major"


# ---------------------------------------------------------------------- dynamics


def test_play_along_keeps_the_real_velocity():
    """Review fix (Phase 6): the MIDI service sends "vel"; play-along logged None before."""
    _, ev = drive(songs.get("amazing-grace-smooth"), hands=("R", "L"))
    notes = of(ev, "practice_end")[0]["log"]["notes"]
    assert {n["vel"] for n in notes if n["hand"] == "R"} == {86} and {n["vel"] for n in notes if n["hand"] == "L"} == {50}


def test_dynamics_balance_and_soft_parts():
    ag = songs.get("amazing-grace-smooth")
    _, ev = drive(ag, hands=("R", "L"))
    d = dynamics.analyze(ag, of(ev, "practice_end")[0]["log"], [20, 110])
    assert d["balance"]["ok"] and d["score"] == 100
    _, ev = drive(ag, hands=("R", "L"), vel={"R": 70, "L": 100})
    d = dynamics.analyze(ag, of(ev, "practice_end")[0]["log"], [20, 110])
    assert not d["balance"]["ok"] and d["tips"][0] == dynamics.TEXTS["balance_low"]
    fe = songs.get("fur-elise")  # a soft song (vel 56): played loud = a tip for each part
    _, ev = drive(fe, hands=("R", "L"), vel={"R": 112, "L": 104})
    d = dynamics.analyze(fe, of(ev, "practice_end")[0]["log"], [20, 120])
    assert [p["want"] for p in d["parts"]] == ["soft", "soft"] and not any(p["ok"] for p in d["parts"])
    assert "Play Part 1 softly." in " ".join(d["tips"])
    _, ev = drive(fe, hands=("R", "L"))
    d = dynamics.analyze(fe, of(ev, "practice_end")[0]["log"], [20, 120])
    assert all(p["ok"] for p in d["parts"])
    assert dynamics.analyze(fe, {"notes": [{"grade": "perfect", "vel": None, "hand": "R", "start": 0}]}) is None


def test_dynamics_none_when_touch_response_is_off():
    ag = songs.get("amazing-grace-smooth")
    _, ev = drive(ag, hands=("R", "L"), vel={"R": 100, "L": 100})  # one value for every key
    log = of(ev, "practice_end")[0]["log"]
    assert dynamics.analyze(ag, log, [20, 110]) is None and dynamics.analyze(ag, log) is None
    _, ev = drive(ag, hands=("R", "L"), vel={"R": 100, "L": 98})  # less than SPREAD_MIN apart
    assert dynamics.analyze(ag, of(ev, "practice_end")[0]["log"]) is None


def _course_result(c, ev):
    published = []
    orig = c.hub.publish
    c.hub.publish = lambda e: (published.append(e), orig(e))
    c.riyaz["practice"].sink(of(ev, "practice_end")[0])
    c.riyaz["flush_results"]()
    c.hub.publish = orig
    return [e for e in published if e.get("type") == "course"][-1]


def test_no_dynamics_tips_before_level9(client):
    c = client
    _, ev = drive(songs.get("amazing-grace-smooth"), hands=("R", "L"), vel={"R": 70, "L": 100})
    assert c.riyaz["course"].user_level() < dynamics.FROM_LEVEL
    assert _course_result(c, ev).get("dynamics") is None
    a = c.riyaz["store"].attempts(kind="song", item="amazing-grace-smooth")[0]
    assert "dynamics" not in a["data"]
    c.riyaz["store"].mark_skill(dynamics.SKILL)  # the lesson is done: the tips start
    assert _course_result(c, ev)["dynamics"]["balance"]["ok"] is False


def test_dynamics_in_the_course_result(client):
    c = client
    c.riyaz["store"].mark_skill(dynamics.SKILL)
    published = []
    orig = c.hub.publish
    c.hub.publish = lambda e: (published.append(e), orig(e))
    _, ev = drive(songs.get("amazing-grace-smooth"), hands=("R", "L"), vel={"R": 70, "L": 100})
    c.riyaz["practice"].sink(of(ev, "practice_end")[0])
    c.riyaz["flush_results"]()
    c.hub.publish = orig
    res = [e for e in published if e.get("type") == "course"][-1]
    assert res["dynamics"]["balance"]["ok"] is False
    a = c.riyaz["store"].attempts(kind="song", item="amazing-grace-smooth")[0]
    assert a["data"]["dynamics"]["balance"]["ok"] is False
    # The weekly summary turns it into a tip.
    w = c.get("/api/coach/week").json()
    assert w["data"]["left_too_loud"] == 1 and coach.TIPS["loud_left"] in w["rule"]["tips"]


# ---------------------------------------------------------------------- foot switch (CC 64)


def test_pedal_moment_is_hidden_and_optional_without_a_pedal(client):
    c = client
    cr = c.riyaz["course"]
    assert not cr.pedal_seen()
    m = [x["id"] for x in c.get("/api/course/moments/fur-elise").json()["moments"]]
    assert m == ["arpeggio"]  # no pedal moment
    st = c.get("/api/course").json()
    lv9 = st["levels"][8]
    assert all(k["id"] != "pedal" for s in lv9["songs"] for k in s["skills"]) and not st["pedal_seen"]
    # Skip forward never needs the pedal moment.
    assert "The foot switch (optional)" not in c.get("/api/course/skip/10").json()["needed"]
    # A CC 64 from the keyboard: the moment shows (and stays optional).
    c.riyaz["midi"].sink({"type": "cc", "control": 64, "value": 127, "ch": 1, "t": 0.0})
    assert c.get("/api/pedal").json() == {"seen": True} and c.riyaz["store"].get("pedal.seen") is True
    m = c.get("/api/course/moments/fur-elise").json()["moments"]
    assert [x["id"] for x in m] == ["pedal", "arpeggio"] and m[0]["optional"]


def test_cc64_up_does_not_count_as_a_pedal_and_forget(client):
    """Some keyboards send one CC 64 = 0 with no foot switch: only a value of 64 or more counts."""
    c = client
    for v in (0, 1, 63):
        c.riyaz["midi"].sink({"type": "cc", "control": 64, "value": v, "ch": 1, "t": 0.0})
    assert c.get("/api/pedal").json() == {"seen": False} and not c.riyaz["store"].get("pedal.seen", False)
    assert [x["id"] for x in c.get("/api/course/moments/fur-elise").json()["moments"]] == ["arpeggio"]
    c.riyaz["midi"].sink({"type": "cc", "control": 64, "value": 64, "ch": 1, "t": 0.1})
    assert c.get("/api/pedal").json() == {"seen": True}
    # Settings "Forget the foot switch".
    assert c.post("/api/pedal/forget", headers=EVIL).status_code == 403
    assert c.post("/api/pedal/forget", headers=OWN).json() == {"seen": False}
    assert c.get("/api/pedal").json() == {"seen": False} and c.riyaz["store"].get("pedal.seen") is False
    assert [x["id"] for x in c.get("/api/course/moments/fur-elise").json()["moments"]] == ["arpeggio"]
    # The page shows the foot switch only on a value of 64 or more, and has the Settings button.
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    app_js = (root / "static" / "app.js").read_text()
    assert '&& e.value >= 64) $("pedal-box").classList.remove("hidden")' in app_js
    assert '&& e.value >= 64) $("pr-pedal").classList.remove("hidden")' in (root / "static" / "js" / "practice.js").read_text()
    assert 'id="pedal-forget"' in (root / "static" / "index.html").read_text()


def test_disconnect_cc64_does_not_count_as_a_pedal(client):
    c = client
    c.riyaz["midi"].sink({"type": "cc", "control": 64, "value": 0, "ch": 1, "t": 0.0, "reason": "disconnect"})
    assert c.get("/api/pedal").json() == {"seen": False}


def test_level_9_and_10_finish_with_no_pedal_ever(client):
    """The user has no foot switch: Level 9 and 10 finish, no pedal message ever comes."""
    from tests.test_ladder import _play_entry

    c = client
    c.post("/api/course/skip", json={"level": 9}, headers=OWN)
    for e in course.ladder_entries():
        if e["level"] >= 9:
            r = _play_entry(c, e)
            assert r["done"], e["key"]
    st = c.get("/api/course").json()
    assert st["all_done"] and not st["pedal_seen"] and "pedal" not in st["skills_done"]


def test_pedal_drill_steps():
    events = []
    clk = Clock()
    d = Drill(events.append, now=clk)
    steps = course.content()["skills"]["pedal"]["steps"]
    d.start({"kind": "steps", "steps": steps, "tries": 1, "id": "skill:pedal"})
    d.on_midi({"type": "note_on", "pitch": 60, "vel": 80, "t": 1.0})
    assert d.state()["last"] == "pedal_up" and d.state()["step"] == 0
    d.on_midi({"type": "note_off", "pitch": 60, "t": 1.1})
    d.on_midi({"type": "cc", "control": 64, "value": 127, "t": 1.2})
    for i, p in enumerate((60, 64, 67)):
        d.on_midi({"type": "note_on", "pitch": p, "vel": 80, "t": 2.0 + i})
        d.on_midi({"type": "note_off", "pitch": p, "t": 2.1 + i})
    d.on_midi({"type": "note_on", "pitch": 60, "vel": 80, "t": 6.0})
    assert d.state()["last"] == "pedal_down"  # the last step: the foot must be up
    d.on_midi({"type": "note_off", "pitch": 60, "t": 6.1})
    d.on_midi({"type": "cc", "control": 64, "value": 0, "t": 6.2})
    d.on_midi({"type": "note_on", "pitch": 60, "vel": 80, "t": 7.0})
    assert d.state()["status"] == "passed"


def test_session_at_levels_9_and_10_has_no_pedal_step(client):
    c = client
    c.post("/api/course/skip", json={"level": 9}, headers=OWN)
    s = c.post("/api/session/start", json={"minutes": 10}, headers=OWN).json()
    song = s["plan"]["blocks"][1]
    assert song["song_id"] == "fur-elise" and [b["kind"] for b in s["plan"]["blocks"]] == ["warmup", "song", "review", "intuition"]
    c.post("/api/course/skip", json={"level": 10}, headers=OWN)
    s = c.post("/api/session/start", json={"minutes": 10}, headers=OWN).json()
    song = s["plan"]["blocks"][1]
    assert song["song_id"] == "happy-birthday" and song["task"] == "lead" and song["steps"][0]["lead"]


def test_session_transpose_task_uses_a_new_key(client):
    from tests.test_ladder import _play_entry

    c = client
    c.post("/api/course/skip", json={"level": 10}, headers=OWN)
    for e in course.ladder_entries():
        if e["level"] == 10 and e["task"] == "lead":
            _play_entry(c, e)
    s = c.post("/api/session/start", json={"minutes": 10}, headers=OWN).json()
    song = s["plan"]["blocks"][1]
    assert song["task"] == "transpose" and song["song_id"].startswith("my-when-the-saints-in-")
    assert songs.get(song["song_id"])["version_of"]["kind"] == "transpose"


# ---------------------------------------------------------------------- recorder


def _record(rec, clk, notes):
    rec.start()
    for t, kind, p, v in notes:
        clk.t = t
        if kind == "cc":
            rec.on_midi({"type": "cc", "control": 64, "value": v, "t": t})
        else:
            rec.on_midi({"type": "note_on" if kind == "on" else "note_off", "pitch": p, "vel": v, "t": t})
    return rec.stop()


def test_recorder_saves_in_the_data_folder_and_exports_midi(data_dir):
    clk = Clock()
    events = []
    rec = recorder_mod.Recorder(events.append, now=clk)
    t0 = clk.t
    tune = [(60, 0.0, 0.4), (64, 0.5, 0.9), (67, 1.0, 1.9)]
    notes = [(t0 + 0.2, "cc", 64, 127)]
    for p, a, b in tune:
        notes += [(t0 + a, "on", p, 90), (t0 + b, "off", p, 0)]
    notes.sort()
    st = _record(rec, clk, notes)
    rid = st["saved"]["id"]
    path = data_dir / "recordings" / f"{rid}.json"
    assert path.is_file() and st["saved"]["notes"] == 3 and st["saved"]["pedal"]
    assert recorder_mod.Recorder.list()[0]["id"] == rid
    mid_path = recorder_mod.Recorder.export(rid)
    assert mid_path == data_dir / "recordings" / f"{rid}.mid"
    mf = mido.MidiFile(mid_path)
    t, ons = 0.0, []
    for msg in mf:
        t += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            ons.append((msg.note, round(t, 2), msg.velocity))
    assert ons == [(60, 0.0, 90), (64, 0.5, 90), (67, 1.0, 90)]
    assert any(m.type == "control_change" and m.control == 64 for m in mf.tracks[0])
    # Round trip through the MIDI importer: the same keys as a song.
    song = midi_import.import_file(mid_path.read_bytes(), "rec.mid", title="My recording")
    assert [n["pitch"] for n in sorted(song["notes"], key=lambda n: n["start"])] == [60, 64, 67]
    starts = sorted(n["start"] for n in song["notes"])
    assert starts[1] - starts[0] == pytest.approx(1.0) and starts[2] - starts[1] == pytest.approx(1.0)  # 120 bpm: 0.5 s = 1 beat
    assert recorder_mod.Recorder.delete(rid) and not path.exists() and not mid_path.exists()


def test_recorder_empty_and_bad_ids(data_dir):
    rec = recorder_mod.Recorder(lambda e: None, now=Clock())
    rec.start()
    assert rec.stop()["saved"] is None and recorder_mod.Recorder.list() == []
    for bad in ("../riyaz", "rec-1/../../x", "x"):
        with pytest.raises(recorder_mod.RecorderError):
            recorder_mod.Recorder.get(bad)


class FakeMidi:
    channel = 0

    def __init__(self):
        self.sent = []

    def note_message(self, pitch, velocity):
        return mido.Message("note_on", note=pitch, velocity=velocity)

    def send(self, msg):
        self.sent.append(msg)
        return True


def test_recorder_plays_on_the_keyboard_only_when_asked(data_dir):
    from riyaz.practice import EchoGuard

    clk = Clock()
    rec = recorder_mod.Recorder(lambda e: None)
    rec.now = clk
    st = _record(rec, clk, [(clk.t, "on", 60, 80), (clk.t + 0.05, "off", 60, 0), (clk.t + 0.06, "on", 62, 70),
                            (clk.t + 0.1, "off", 62, 0)])
    with pytest.raises(recorder_mod.RecorderError):
        rec.play_keyboard(st["saved"]["id"])  # no MIDI service
    import time

    rec.now = time.perf_counter
    rec.midi = FakeMidi()
    rec.echo = EchoGuard()
    rec.play_keyboard(st["saved"]["id"])
    rec._thread.join(timeout=3)
    sent = [(m.note, m.velocity) for m in rec.midi.sent if m.type == "note_on"]
    assert sent == [(60, 80), (60, 0), (62, 70), (62, 0)] and rec.state()["playing"] is None
    assert [r for r, _ in rec.echo._sent] == [60, 62]  # the echo guard knows the sent notes


def test_recorder_api(client):
    c = client
    assert c.post("/api/recorder/start", headers=EVIL).status_code == 403
    assert c.post("/api/recorder/start", headers=OWN).json()["recording"]
    c.riyaz["midi"].sink({"type": "note_on", "pitch": 60, "vel": 80, "t": 1.0, "raw": 60, "ch": 1})
    c.riyaz["midi"].sink({"type": "note_off", "pitch": 60, "t": 1.5, "raw": 60, "ch": 1})
    st = c.post("/api/recorder/stop", headers=OWN).json()
    rid = st["saved"]["id"]
    lst = c.get("/api/recorder").json()["recordings"]
    assert [r["id"] for r in lst] == [rid]
    assert c.get(f"/api/recordings/{rid}").json()["events"][0][1] == "on"
    r = c.get(f"/api/recordings/{rid}/midi")
    assert r.status_code == 200 and r.content[:4] == b"MThd" and "attachment" in r.headers["content-disposition"]
    assert c.post(f"/api/recordings/{rid}/play-keyboard", headers=OWN).status_code == 409  # no keyboard output
    song = c.post(f"/api/recordings/{rid}/import", headers=OWN).json()["song"]
    assert song["title"].startswith("Recording") and songs.get(song["id"]) is not None
    assert c.get("/api/recordings/..%2Fx").status_code == 404
    assert c.post(f"/api/recordings/{rid}/delete", headers=OWN).json()["ok"]
    assert c.get(f"/api/recordings/{rid}").status_code == 404


def test_recorder_close_saves_an_open_recording(data_dir):
    clk = Clock()
    rec = recorder_mod.Recorder(lambda e: None, now=clk)
    rec.start()
    rec.on_midi({"type": "note_on", "pitch": 60, "vel": 80, "t": clk.t})
    clk.t += 1.0
    rec.close()  # the app quits while it records
    assert not rec.recording and rec.last_saved
    assert [r["id"] for r in recorder_mod.Recorder.list()] == [rec.last_saved]


def test_recorder_list_reads_only_the_index(data_dir):
    clk = Clock()
    rec = recorder_mod.Recorder(lambda e: None, now=clk)
    ids = []
    for i in range(3):
        clk.t += 2.0
        ids.append(_record(rec, clk, [(clk.t, "on", 60 + i, 80), (clk.t + 0.1, "off", 60 + i, 0)])["saved"]["id"])
    folder = data_dir / "recordings"
    assert set(json.loads((folder / "index.json").read_text())) == set(ids)
    # The list does not open the recordings: a recording file that cannot be read is still listed.
    (folder / f"{ids[0]}.json").write_text("not json")
    assert {r["id"] for r in recorder_mod.Recorder.list()} == set(ids)
    # No index (an old folder): the list makes it again from the files that can be read.
    (folder / "index.json").unlink()
    assert {r["id"] for r in recorder_mod.Recorder.list()} == set(ids[1:])
    assert (folder / "index.json").is_file()
    assert recorder_mod.Recorder.delete(ids[1])
    assert ids[1] not in json.loads((folder / "index.json").read_text())
    assert [r["id"] for r in recorder_mod.Recorder.list()] == [ids[2]]


def test_other_key_activities_stop_the_recorder_playback(client):
    c = client
    rec = c.riyaz["recorder"]
    stopped = []
    rec.stop_playback = lambda: (stopped.append(1), setattr(rec, "playing", None), rec.state())[-1]
    rec.playing = "rec-20260101-000000"
    r = c.post("/api/practice/start", json={"song_id": "mary-had-a-little-lamb", "mode": "wait"}, headers=OWN)
    assert r.status_code == 200 and stopped == [1]
    c.post("/api/practice/stop", headers=OWN)
    rec.playing = "rec-20260101-000000"
    assert c.post("/api/settings/latency/start", headers=OWN).status_code == 200
    assert stopped == [1, 1] and rec.playing is None
    c.riyaz["tapcheck"].cancel()


# ---------------------------------------------------------------------- weekly coach


class _FakeOllama(BaseHTTPRequestHandler):
    calls: list = []
    reply = "**Good week!** You practiced 3 days. Play the chord ear games."
    models = [{"name": "llama3.2:3b"}]

    def log_message(self, *a):
        pass

    def _send(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        type(self).calls.append(("GET", self.path, None))
        self._send({"models": type(self).models})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append(("POST", self.path, body))
        self._send({"response": type(self).reply, "done": True})


@pytest.fixture
def fake_ollama(monkeypatch):
    srv = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    _FakeOllama.calls = []
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    monkeypatch.setenv("RIYAZ_OLLAMA_PORT", str(srv.server_address[1]))
    yield _FakeOllama
    srv.shutdown()
    srv.server_close()


def _free_port():
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_rule_summary_with_and_without_practice(store):
    data = coach.week_data(store, None, "2026-11-14")
    r = coach.rule_summary(data)
    assert r["lines"] == ["You did not practice in the last 7 days."] and r["tips"] == [coach.TIPS["start"]]
    store.add_seconds("2026-11-12", 600)
    store.add_seconds("2026-11-14", 300)
    store.add_attempt(kind="song", item="ode-to-joy", day="2026-11-14", completed=True, accuracy=90,
                      data={"mode": "play", "score": {"total": 91, "accuracy": 95, "timing": 40, "hit": 10}})
    data = coach.week_data(store, None, "2026-11-14")
    assert data["practice_days"] == 2 and data["minutes"] == 15.0 and data["songs"][0]["best_score"] == 91
    r = coach.rule_summary(data)
    assert r["lines"][0] == "You practiced on 2 of the last 7 days, 15 minutes in all."
    assert 'Your best score is 91 in "Ode to Joy".' in " ".join(r["lines"])
    assert coach.TIPS["days"] in r["tips"] and coach.TIPS["rhythm"] in r["tips"]  # timing is the weakest skill
    # JSON only: numbers, titles, skill names (no audio, no paths).
    assert json.loads(json.dumps(data)) == data and "/" not in json.dumps(data["songs"])


def test_coach_texts_are_ste_and_use_no_locked_terms():
    from tests.test_course import TERM_RE

    for t in coach.all_texts() + dynamics.all_texts():
        plain = course.render_text(t, set())
        assert plain[0].isupper() and plain.rstrip('"').endswith("."), t
        for s in re.split(r"(?<=[.:])\s+", plain):
            assert len(s.split()) <= 20, s
        visible = course.TERM_MARK.sub("", plain)
        for tid, rx in TERM_RE.items():
            assert not rx.search(visible), (tid, t)


def test_coach_with_a_fake_local_ollama(store, fake_ollama):
    c = coach.Coach()
    assert c.base.startswith("http://127.0.0.1:") and c.status()["running"] and c.status()["model_ok"]
    data = coach.week_data(store, None, "2026-11-14")
    text = c.summary(data, unlocked=set())
    # No markdown, and the locked term "chord" gets its plain word (PLAN 7.4).
    assert text.startswith("Good week!") and "**" not in text and "chord" not in text.lower()
    post = [x for x in fake_ollama.calls if x[0] == "POST"][0]
    assert post[1] == "/api/generate" and post[2]["model"] == "llama3.2:3b" and post[2]["stream"] is False
    assert '"practice_days": 0' in post[2]["prompt"]  # the progress JSON, nothing else
    # Off by default: the weekly card does not call Ollama.
    fake_ollama.calls.clear()
    w = coach.weekly(store, None, "2026-11-14")
    assert w["coach"] == "off" and w["llm"] is None and fake_ollama.calls == []
    coach.set_settings(store, {"enabled": True})
    w = coach.weekly(store, None, "2026-11-14")
    assert w["coach"] == "ok" and w["llm"].startswith("Good week!")
    # A model that Ollama does not have.
    coach.set_settings(store, {"model": "other:1b"})
    w = coach.weekly(store, None, "2026-11-14")
    assert w["coach"] == "not_running" and "other:1b" in w["coach_text"]
    assert coach.set_settings(store, {"model": "bad model; rm -rf"})["model"] == "other:1b"  # not accepted


def test_coach_with_no_server(store, monkeypatch):
    monkeypatch.setenv("RIYAZ_OLLAMA_PORT", str(_free_port()))
    c = coach.Coach(status_timeout=0.5)
    assert c.status() == {"running": False, "models": [], "model_ok": False}
    with pytest.raises(coach.CoachUnavailable) as exc:
        c.summary(coach.week_data(store, None, "2026-11-14"))
    assert str(exc.value) == coach.NOT_RUNNING
    coach.set_settings(store, {"enabled": True})
    w = coach.weekly(store, None, "2026-11-14")
    assert w["coach"] == "not_running" and w["rule"]["lines"] and w["coach_text"] == coach.NOT_RUNNING


def test_rule_summary_titles_are_not_term_marks():
    """A song title like "[[xyz]]" is data, not a term mark: no KeyError, no mark on the page."""
    data = {"today": "2026-11-14", "days": [], "practice_days": 2, "minutes": 10, "sessions": 1, "streak": 0,
            "level": 3, "songs": [{"title": "[[xyz]] song", "runs": 1, "best_score": 70, "best_wait": None}],
            "songs_done": ["[[chord|x]]", "[[major_minor]]"], "ear_games": 0, "ear_score": None, "skills": [],
            "left_too_loud": 0}
    r = coach.rule_summary(data, set())
    text = " ".join(r["lines"])
    assert "xyz" in text and not course.TERM_MARK.search(text)
    r = coach.rule_summary(data, {"chord", "major_minor"})
    assert not course.TERM_MARK.search(" ".join(r["lines"]))


def test_llm_text_plain_words_keep_plural_and_capital():
    out = coach.clean("Chords are fun. Play 2 chords. A minor chord. Major keys.", set())
    assert out == "Keys together are fun. Play 2 keys together. A sad sound these 3 keys together. Happy sound keys."
    assert coach.clean("Play the chords.", {"chord"}) == "Play the chords."


class _Redirect(BaseHTTPRequestHandler):
    target = ""

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", type(self).target + self.path)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_POST = do_GET


class _Slow(BaseHTTPRequestHandler):
    """Sends one byte each 0.1 s: each read is fast, the whole answer never ends."""

    def log_message(self, *a):
        pass

    def do_GET(self):
        import time

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            for _ in range(40):
                self.wfile.write(b" ")
                self.wfile.flush()
                time.sleep(0.1)
        except OSError:
            pass


def _serve(handler):
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_coach_refuses_redirects(fake_ollama):
    srv = _serve(_Redirect)
    _Redirect.target = f"http://127.0.0.1:{coach._port()}"  # the fake Ollama answers there
    try:
        c = coach.Coach(port=srv.server_address[1], status_timeout=1.0)
        assert c.status()["running"] is False
        assert not fake_ollama.calls  # the redirect was not followed
    finally:
        srv.shutdown()
        srv.server_close()


def test_coach_request_has_one_deadline():
    import time

    srv = _serve(_Slow)
    try:
        c = coach.Coach(port=srv.server_address[1], status_timeout=0.5)
        t0 = time.monotonic()
        assert c.status()["running"] is False
        assert time.monotonic() - t0 < 1.5  # not 4 s (one byte in each 0.1 s read)
    finally:
        srv.shutdown()
        srv.server_close()


def test_coach_api_off_by_default(client, monkeypatch):
    c = client
    monkeypatch.setenv("RIYAZ_OLLAMA_PORT", str(_free_port()))
    assert c.get("/api/settings/coach").json() == {"enabled": False, "model": coach.DEFAULT_MODEL}
    assert c.get("/api/coach/status").json()["running"] is None  # off: no look for Ollama
    w = c.post("/api/coach/summary", headers=OWN).json()
    assert w["coach"] == "off" and w["rule"]["title"] == "Your week"
    assert c.post("/api/settings/coach", json={"enabled": True}, headers=EVIL).status_code == 403
    assert c.post("/api/settings/coach", json={"enabled": True}, headers=OWN).json()["enabled"]
    assert c.get("/api/coach/status").json()["running"] is False
    assert c.post("/api/coach/summary", headers=OWN).json()["coach"] == "not_running"


# ---------------------------------------------------------------------- UI words (PLAN 7.4) for Phase 6


NEW_TERMS = re.compile(r"\b(arpeggios?|inversions?|dynamics|lead sheets?)\b", re.I)


def test_new_ui_has_no_level_9_10_terms(client):
    """The page is visible at Level 1: the Phase 6 UI uses plain words, not the new terms."""
    from tests.test_server import LOCKED, shown_strings

    html = client.get("/").text
    html = re.sub(r"<!--.*?-->|<script.*?</script>|<style.*?</style>", " ", html, flags=re.S)
    visible = re.sub(r"<[^>]+>", " ", html)
    assert not NEW_TERMS.search(visible), NEW_TERMS.search(visible)
    for js in ("/static/js/recorder.js", "/static/js/coach.js", "/static/js/practice.js", "/static/js/course.js",
               "/static/js/today.js", "/static/js/drill.js", "/static/js/renderer.js"):
        for text in shown_strings(client.get(js).text):
            assert not LOCKED.search(text) and not NEW_TERMS.search(text), (js, text)
