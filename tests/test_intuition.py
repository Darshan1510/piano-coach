"""Phase 5b: intuition exercises (PLAN 10, Levels 1-8), their texts (PLAN 7.4), the skill model
(PLAN 9.4) and the intuition block of the daily session (PLAN 9.1). Fake clock, no CoreMIDI.
The end-to-end runs over a CoreMIDI virtual port are in tests/test_midi_virtual.py."""

import random
import re

import pytest
from fastapi.testclient import TestClient

from riyaz import config, course, intuition, skills
from riyaz.course import Course
from riyaz.db import Store
from riyaz.intuition import Intuition, IntuitionError, suggest_chords
from riyaz.server import create_app
from riyaz.session import plan
from tools.fake_player import INTUITION_IDS, intuition_moves

OWN = {"Origin": "http://127.0.0.1:8020"}


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def open_all_levels(store):
    store.course_set("level_floor", 8)
    for t in course.content()["terms"]:
        store.unlock_term(t["id"])


@pytest.fixture
def env(store):
    open_all_levels(store)
    c = Course(store)
    for sid in ("ode-to-joy", "twinkle-twinkle", "jingle-bells"):  # songs that the user played
        store.update_song_progress(sid, accuracy=90.0, full=True, done=False, part_errors={}, t=1.0)
    clk = Clock()
    events = []
    eng = Intuition(events.append, now=clk, threaded=False)
    return c, eng, clk, events


def drive(eng, clk, answer="correct", buttons=False, limit=4000):
    """A player that does intuition_moves() at each state, with a fake clock."""
    done_key = None
    for _ in range(limit):
        st = eng.state()
        if st["status"] == "done":
            return st
        sol = st.get("solution") or {}
        key = (st["round"], st["tries"], st["status"], st["step"], st["last"], (st.get("jam") or {}).get("presses"),
               st.get("tune_count"))
        if st["status"] in ("answer", "jam") and key != done_key:
            done_key = key
            moves = intuition_moves(st, answer)
            if buttons and st["choices"] and "choice" in sol:
                right = sol["choice"]
                wrong = next(c["id"] for c in st["choices"] if c["id"] != right)
                moves = [{"button": right if answer == "correct" else wrong}]
            for m in moves:
                if "button" in m:
                    eng.answer(m["button"])
                elif m.get("tune_done"):
                    eng.tune_done()
                else:
                    clk.t = max(clk.t, m.get("after", 0) + 0.01)
                    for p in m["keys"]:
                        eng.on_midi({"type": "note_on", "pitch": p, "vel": 80, "t": clk.t})
                    clk.t += 0.05
                    for p in m["keys"]:
                        eng.on_midi({"type": "note_off", "pitch": p, "t": clk.t})
                    clk.t += m.get("wait", 0.05)
        clk.t += 0.05
        eng.tick()
    raise AssertionError(f"no end: {eng.state()}")


def spec(c, ex_id, seed=1, song_id="ode-to-joy"):
    from riyaz import songs

    return intuition.make_spec(ex_id, c, random.Random(seed), songs.get(song_id))


# ---------------------------------------------------------------------- each exercise


@pytest.mark.parametrize("ex_id", INTUITION_IDS)
def test_each_exercise_right_answers_score_100(env, ex_id):
    c, eng, clk, events = env
    saved = []
    eng.start(spec(c, ex_id), on_done=lambda sp, s: saved.append(s))
    st = drive(eng, clk, "correct")
    assert st["result"]["score"] == 100, st["result"]
    assert saved and saved[0]["score"] == 100 and saved[0]["skills"] == intuition.exercise(ex_id)["skills"]
    assert not [e for e in events if e["type"] == "intuition_wrong"]


@pytest.mark.parametrize("ex_id", INTUITION_IDS)
def test_each_exercise_wrong_answers_score_0(env, ex_id):
    c, eng, clk, events = env
    eng.start(spec(c, ex_id), on_done=lambda sp, s: None)
    st = drive(eng, clk, "wrong")
    assert st["result"]["score"] == 0, st["result"]
    if ex_id not in ("jam", "add_chords"):
        assert [e for e in events if e["type"] == "intuition_wrong"]
    if ex_id in ("echo", "interval", "chord_shape", "major_minor", "next_chord"):
        # 2 wrong tries in each round, then the app shows the answer.
        assert len([e for e in events if e["type"] == "intuition_wrong"]) == 2 * st["rounds"]
        assert any(e["type"] == "intuition" and e["last"] == "shown" for e in events)


@pytest.mark.parametrize("ex_id", ["interval", "major_minor"])
def test_button_answers(env, ex_id):
    c, eng, clk, _ = env
    eng.start(spec(c, ex_id))
    assert drive(eng, clk, "correct", buttons=True)["result"]["score"] == 100
    eng.start(spec(c, ex_id, seed=2))
    assert drive(eng, clk, "wrong", buttons=True)["result"]["score"] == 0


def test_keys_do_not_count_while_the_app_plays(env):
    c, eng, clk, _ = env
    st = eng.start(spec(c, "echo"))
    assert st["status"] == "listen" and st["play"] and st["play_at"] > clk.t
    first = st["solution"]["keys"][0][0]
    eng.on_midi({"type": "note_on", "pitch": first + 1, "t": clk.t})  # a wrong key while the app plays
    assert eng.state()["tries"] == 0 and eng.state()["status"] == "listen"
    clk.t = st["listen_until"] + 0.01
    eng.tick()
    assert eng.state()["status"] == "answer"
    eng.on_midi({"type": "note_on", "pitch": first, "t": clk.t})
    assert eng.state()["step"] == 1


def test_listen_again_and_one_more_try(env):
    c, eng, clk, _ = env
    st = eng.start(spec(c, "interval"))
    clk.t = st["listen_until"] + 0.1
    eng.tick()
    eng.answer("nope-not-it")  # a wrong button
    st = eng.state()
    assert st["last"] == "wrong" and st["tries"] == 1 and st["status"] == "answer"
    st2 = eng.replay(st["run"])
    assert st2["status"] == "answer" and st2["play_at"] > clk.t and st2["last"] == "replay"
    with pytest.raises(IntuitionError):
        eng.replay(st["run"] + 5)
    eng.answer(st["solution"]["choice"])
    assert eng.state()["right"] == 0 and eng.state()["last"] == "right"  # right, but not at the first try


def test_chord_shape_any_octave_any_order_and_keys_together(env):
    c, eng, clk, _ = env
    st = eng.start(spec(c, "chord_shape"))
    pcs = st["solution"]["pcs"]
    keys = sorted(st["solution"]["keys"])
    up = [keys[1] + 12, keys[0] + 24, keys[2] + 12]  # another order and octave (an inversion)
    for p in up:
        eng.on_midi({"type": "note_on", "pitch": p, "t": clk.t})
        clk.t += 0.1
    assert eng.state()["last"] == "right", (pcs, up)
    # Keys more than 300 ms apart, each lifted: not together.
    clk.t += 2
    eng.tick()
    st = eng.state()
    keys = st["solution"]["keys"]
    for p in keys:
        eng.on_midi({"type": "note_on", "pitch": p, "t": clk.t})
        eng.on_midi({"type": "note_off", "pitch": p, "t": clk.t + 0.05})
        clk.t += 0.5
    assert eng.state()["last"] == "hit"


def test_texts_follow_the_term_unlocks(store):
    """PLAN 7.4: before the unlock, the plain words ("the jump between 2 keys", "happy or sad")."""
    c = Course(store)
    store.course_set("level_floor", 8)
    names = {e["id"]: e["name"] for e in intuition.public_list(c)}
    assert names["interval"] == "The jump between 2 keys" and names["major_minor"] == "Happy or sad"
    assert names["chord_shape"] == "Shapes of 3 keys"
    sp = spec(c, "major_minor")
    labels = [x["label"] for x in sp["rounds"][0]["choices"]]
    assert labels == ["Happy sound", "Sad sound"]
    for t in ("interval", "chord", "major_minor"):
        store.unlock_term(t)
    names = {e["id"]: e["name"] for e in intuition.public_list(c)}
    assert names["interval"] == "[[interval|Interval ear]]" and names["major_minor"] == "[[major_minor|Major or minor]]"
    labels = [x["label"] for x in spec(c, "major_minor")["rounds"][0]["choices"]]
    assert labels == ["[[major_minor|Major: happy]]", "[[major_minor|Minor: sad]]"]


LOCKED_WORDS = {t["id"]: re.compile(rf"\b(?:{t['pattern']})\b", re.I) for t in course.content()["terms"]}


@pytest.mark.parametrize("ex_id", INTUITION_IDS)
def test_round_texts_have_no_locked_term(store, ex_id):
    """Rule 6 for the texts that the rounds make (prompts with names): no term unlocked at all
    (all moments skipped), the exercise still shows plain words."""
    c = Course(store)
    store.course_set("level_floor", 8)
    for sid in ("ode-to-joy", "twinkle-twinkle"):
        store.update_song_progress(sid, accuracy=90.0, full=True, done=False, part_errors={}, t=1.0)
    sp = spec(c, ex_id)
    texts = [sp["name"]] + [r["prompt"] for r in sp["rounds"]] + [x["label"] for r in sp["rounds"] for x in r.get("choices", [])]
    for text in texts:
        for tid, rx in LOCKED_WORDS.items():
            if tid in ("finger_number",):
                continue
            assert not rx.search(text), (ex_id, tid, text)


# ---------------------------------------------------------------------- add chords, jam


def test_suggest_chords_key_and_melody_notes():
    # Ode to Joy, first 4 groups of clicks: C major; the chords contain the first note of each group.
    tune = [{"pitch": p, "dur": 1} for p in (64, 64, 65, 67)], [{"pitch": p, "dur": 1} for p in (67, 65, 64, 62)], \
        [{"pitch": p, "dur": 1} for p in (60, 60, 62, 64)], [{"pitch": 64, "dur": 1.5}, {"pitch": 62, "dur": 0.5}, {"pitch": 62, "dur": 2}]
    out = suggest_chords(list(tune), (0, "major"))
    assert [c["name"] for c in out] == ["C", "G", "C", "G"]
    assert intuition.detect_key([n for seg in tune for n in seg]) == (0, "major")
    # A minor tune: the home chord is minor, the V chord is major (E, with G sharp).
    am = [[{"pitch": p, "dur": 1} for p in (69, 72, 76)], [{"pitch": 68, "dur": 1}, {"pitch": 71, "dur": 2}],
          [{"pitch": 69, "dur": 3}]]
    assert [c["name"] for c in suggest_chords(am, (9, "minor"))] == ["Am", "E", "Am"]


def test_add_chords_with_an_own_tune(env):
    c, eng, clk, _ = env
    st = eng.start(spec(c, "add_chords"))
    assert st["phase"] == "tune" and st["status"] == "answer"
    for p in (67, 69, 71, 72, 74, 72, 71, 67):  # an own tune in G
        eng.on_midi({"type": "note_on", "pitch": p, "t": clk.t})
        clk.t += 0.4
        eng.on_midi({"type": "note_off", "pitch": p, "t": clk.t})
    clk.t += 3.0  # a pause of 2.5 s ends the tune
    eng.tick()
    st = eng.state()
    assert st["phase"] == "chord" and st["rounds"] == 3 and st["glow"] == st["solution"]["keys"]
    assert st["key_text"] and "G" in st["key_text"]
    final = drive(eng, clk, "correct")
    assert final["result"]["score"] == 100 and final["result"]["rounds"] == 2


def test_jam_score_is_the_share_of_keys_from_the_key_family(env):
    c, eng, clk, _ = env
    st = eng.start(spec(c, "jam", song_id="pop-loop"))
    assert st["status"] == "jam" and st["clicks"] and st["chords"] and st["length"] > 20
    pcs = set(st["solution"]["pcs"])
    assert set(p % 12 for p in st["glow"]) == pcs
    clk.t = st["play_at"] + 1
    inside = [p for p in range(60, 72) if p % 12 in pcs]
    outside = [p for p in range(60, 72) if p % 12 not in pcs]
    for p in inside[:6] + outside[:2] + inside[:4]:
        eng.on_midi({"type": "note_on", "pitch": p, "t": clk.t})
        clk.t += 0.5
    clk.t = st["play_at"] + st["length"] + 0.1
    eng.tick()
    res = eng.state()["result"]
    assert res["presses"] == 12 and res["inside"] == 10 and res["score"] == round(100 * 10 / 12)


def test_jam_with_few_keys_scores_less(env):
    c, eng, clk, _ = env
    st = eng.start(spec(c, "jam"))
    clk.t = st["play_at"] + 1
    for p in st["solution"]["keys"][:4]:
        eng.on_midi({"type": "note_on", "pitch": p, "t": clk.t})
    clk.t = st["play_at"] + st["length"] + 0.1
    eng.tick()
    assert eng.state()["result"]["score"] == 50  # 100 % of 4 keys, 4 of the 8 keys asked for


def test_keyboard_speaker_sends_the_notes_with_the_echo_guard(env):
    from riyaz.practice import EchoGuard

    c, eng, clk, _ = env

    class Midi:
        sent = []

        def note_message(self, p, v):
            import mido

            return mido.Message("note_on", note=p, velocity=v)

        def send(self, msg):
            self.sent.append((clk.t, msg.note, msg.velocity))

    eng.midi, eng.echo = Midi(), EchoGuard()
    st = eng.start(spec(c, "major_minor"), output="keyboard")
    assert st["output"] == "keyboard"
    for _ in range(80):
        clk.t += 0.05
        eng.tick()
    ons = [x for x in Midi.sent if x[2] > 0]
    assert sorted(p for _, p, _ in ons) == sorted(st["solution"]["keys"])
    assert all(abs(t - st["play_at"]) < 0.06 for t, _, _ in ons)
    assert len([x for x in Midi.sent if x[2] == 0]) == 3
    # The keyboard sends the notes back: the echo guard knows them.
    assert all(eng.echo.is_echo(True, 0, p, t) for t, p, _ in ons)


# ---------------------------------------------------------------------- skill model, session, server


def test_results_feed_the_skill_model(store):
    store.add_attempt(kind="intuition", item="major_minor", day="2026-11-14", completed=True, accuracy=50,
                      data={"score": 50, "skills": ["ear", "chords"]})
    store.add_attempt(kind="intuition", item="jam", day="2026-11-14", completed=True, accuracy=90,
                      data={"score": 90, "skills": ["scales"]})
    res = skills.results(store)
    assert res["ear"] == [50.0] and res["chords"] == [50.0] and res["scales"] == [90.0]
    vals = {s["id"]: s["value"] for s in skills.model(store)}
    assert vals["scales"] == 90.0 and vals["ear"] == 50.0


def test_session_picks_an_open_exercise_for_the_weakest_skill(store):
    c = Course(store)
    # Level 1: only "Find the key" is open.
    b = plan(store, c)["blocks"][3]
    assert b["exercise"] == "find_key" and b["drill"]["kind"] == "find_key"
    store.course_set("level_floor", 8)
    b = plan(store, c)["blocks"][3]
    assert b["exercise"] != "find_key" and "intuition" in b and b["intuition"]["id"] == b["exercise"]
    ex = intuition.exercise(b["exercise"])
    assert ex["level"] <= 8 and b["focus"] in ex["skills"]
    # A skill without results is the weakest (a new game). Then the weakest by results.
    for k in ("keys", "ear", "chords"):
        store.add_attempt(kind="intuition", item={"keys": "find_key", "ear": "echo", "chords": "chord_shape"}[k],
                          day="2026-11-14", completed=True, data={"score": 90, "skills": [k]})
    assert plan(store, c)["blocks"][3]["focus"] == "scales" and plan(store, c)["blocks"][3]["exercise"] == "jam"
    store.add_attempt(kind="intuition", item="jam", day="2026-11-14", completed=True, data={"score": 95, "skills": ["scales"]})
    store.add_attempt(kind="intuition", item="echo", day="2026-11-14", completed=True, data={"score": 10, "skills": ["ear"]})
    b = plan(store, c)["blocks"][3]
    assert b["focus"] == "ear" and "ear" in intuition.exercise(b["exercise"])["skills"]
    # Level 3: only exercises of Levels 1-3.
    store.course_set("level_floor", 3)
    assert intuition.exercise(plan(store, c)["blocks"][3]["exercise"])["level"] <= 3


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as cl:
        cl.riyaz = app.state.riyaz
        yield cl


def test_intuition_api(client):
    c = client
    lst = c.get("/api/intuition").json()
    by = {e["id"]: e for e in lst["exercises"]}
    assert set(by) == {"find_key", *INTUITION_IDS}
    assert by["find_key"]["open"] and not by["echo"]["open"] and by["find_key"]["kind"] == "drill"
    r = c.post("/api/intuition/start", json={"id": "echo"}, headers=OWN)
    assert r.status_code == 409 and "Level 2" in r.json()["detail"]
    assert c.post("/api/intuition/start", json={"id": "nope"}, headers=OWN).status_code == 404
    assert c.post("/api/intuition/start", json={"id": "echo"}, headers={"Origin": "http://evil.example"}).status_code == 403
    c.riyaz["store"].course_set("level_floor", 8)
    r = c.post("/api/intuition/start", json={"id": "major_minor", "seed": 3}, headers=OWN).json()
    assert r["status"] == "listen" and r["id"] == "major_minor" and len(r["choices"]) == 2
    eng = c.riyaz["intuition"]
    import time

    while eng.state()["status"] == "listen":
        time.sleep(0.05)
    st = c.post("/api/intuition/answer", json={"run": r["run"], "choice": r["solution"]["choice"]}, headers=OWN).json()
    assert st["right"] == 1 and st["last"] == "right"
    assert c.post("/api/intuition/answer", json={"run": r["run"] + 9, "choice": "major"}, headers=OWN).status_code == 400
    assert c.post("/api/intuition/stop", headers=OWN).json()["status"] == "stopped"
    # Keys from the server sink (as from the keyboard) reach the exercise.
    r = c.post("/api/intuition/start", json={"id": "chord_shape", "seed": 1}, headers=OWN).json()
    sink = c.riyaz["midi"].sink
    for p in r["solution"]["keys"]:
        sink({"type": "note_on", "pitch": p, "vel": 80, "t": time.perf_counter()})
    assert c.get("/api/intuition/state").json()["right"] == 1
    for p in r["solution"]["keys"]:
        sink({"type": "note_off", "pitch": p, "t": time.perf_counter()})
    # The keyboard speaker needs a MIDI output.
    r = c.post("/api/intuition/start", json={"id": "echo", "output": "keyboard"}, headers=OWN)
    assert r.status_code == 409 and "keyboard speaker" in r.json()["detail"]


def test_a_finished_exercise_is_saved_for_the_skill_model(client):
    c = client
    c.riyaz["store"].course_set("level_floor", 8)
    eng = c.riyaz["intuition"]
    r = c.post("/api/intuition/start", json={"id": "chord_shape", "seed": 4, "rounds": 2}, headers=OWN).json()
    import time

    for _ in range(2):
        st = c.get("/api/intuition/state").json()
        while st["status"] != "answer":
            time.sleep(0.05)
            st = c.get("/api/intuition/state").json()
        for p in st["solution"]["keys"]:
            c.riyaz["midi"].sink({"type": "note_on", "pitch": p, "vel": 80, "t": time.perf_counter()})
        for p in st["solution"]["keys"]:
            c.riyaz["midi"].sink({"type": "note_off", "pitch": p, "t": time.perf_counter()})
    deadline = time.monotonic() + 5
    while eng.state()["status"] != "done" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert eng.state()["result"]["score"] == 100
    a = c.riyaz["store"].attempts(kind="intuition")
    assert a and a[0]["item"] == "chord_shape" and a[0]["data"]["skills"] == ["chords"]
    prog = c.get("/api/progress").json()
    assert next(s for s in prog["skills"] if s["id"] == "chords")["value"] == 100.0
    by = {e["id"]: e for e in c.get("/api/intuition").json()["exercises"]}
    assert by["chord_shape"]["runs"] == 1 and by["chord_shape"]["last"] == 100


# ------------------------------------------------------------------- Phase 5 review fixes (B1, B2, B4)


def test_next_chord_pairs_are_shuffled_for_every_round_count(env):
    c, _eng, _clk, _ = env
    def pairs(seed, n):
        rs = intuition.make_spec("next_chord", c, random.Random(seed), rounds=n)["rounds"]
        return [(tuple(r["solution"]["roman"]), tuple(x["pitch"] for x in r["play"])) for r in rs]
    twelve = pairs(1, 12)
    assert len(set(twelve)) == 12  # each key with each pattern once
    assert len({tuple(pairs(s, 4)) for s in range(1, 9)}) > 4  # 4 rounds: not the same order each time
    assert {p[1][0] % 12 for s in range(1, 9) for p in pairs(s, 3)} != {pairs(1, 3)[0][1][0] % 12}


def test_find_the_tune_round_is_right_only_when_each_key_is_right_at_the_first_try(env):
    c, eng, clk, _ = env
    sp = spec(c, "find_melody")
    sp["rounds"] = sp["rounds"][:2]
    eng.start(sp)
    for rnd in range(2):
        while eng.state()["status"] != "answer":
            clk.t += 0.05
            eng.tick()
        keys = [k[0] for k in eng.state()["solution"]["keys"]]
        for i, p in enumerate(keys):
            if rnd == 1 and i == 1:  # one wrong key in round 2
                eng.on_midi({"type": "note_on", "pitch": p + 1 if (p + 1) % 12 != p % 12 else p + 2, "vel": 80, "t": clk.t})
                clk.t += 0.05
            eng.on_midi({"type": "note_on", "pitch": p, "vel": 80, "t": clk.t})
            clk.t += 0.05
            eng.on_midi({"type": "note_off", "pitch": p, "t": clk.t})
            clk.t += 0.05
    for _ in range(400):
        if eng.state()["status"] == "done":
            break
        clk.t += 0.05
        eng.tick()
    res = eng.state()["result"]
    assert res["first"] == [True, False]
    assert res["right"] == res["total"] - 1


def test_one_key_activity_at_a_time(client):
    """B2: each start (practice, ear game, the "Find the key" drill, the tap check) stops the others."""
    c = client
    c.riyaz["store"].course_set("level_floor", 8)
    r = c.post("/api/drill/start", json={"source": "find_key"}, headers=OWN)
    assert r.status_code == 200 and c.riyaz["drill"].state()["status"] == "active"
    assert c.post("/api/intuition/start", json={"id": "chord_shape"}, headers=OWN).status_code == 200
    assert c.riyaz["drill"].state()["status"] == "stopped"
    assert c.post("/api/practice/start", json={"song_id": "ode-to-joy", "mode": "wait"}, headers=OWN).status_code == 200
    assert c.riyaz["intuition"].state()["status"] == "stopped"
    assert c.post("/api/settings/latency/start", headers=OWN).status_code == 200
    assert c.riyaz["practice"].song is None and c.riyaz["tapcheck"].active
    assert c.post("/api/drill/start", json={"source": "find_key"}, headers=OWN).status_code == 200
    assert not c.riyaz["tapcheck"].active
    assert c.post("/api/intuition/start", json={"id": "chord_shape"}, headers=OWN).status_code == 200
    assert c.post("/api/settings/latency/start", headers=OWN).status_code == 200
    assert c.riyaz["intuition"].state()["status"] == "stopped"
    c.post("/api/settings/latency/reset", headers=OWN)
