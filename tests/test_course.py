"""Phase 3b: course content and words (PLAN 7.4, 8), drills, skill moments, song ladder, daily
session, streak and reminder (PLAN 9.1, 9.2). No CoreMIDI: key events go into the server sink."""

import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient

from riyaz import config, course, songs
from riyaz.course import Course, song_done
from riyaz.db import Store
from riyaz.drill import Drill
from riyaz.practice import Practice
from riyaz.server import create_app
from riyaz.session import Activity, Reminder, Sessions, block_minutes, calendar, plan, streak, warmup_pattern

OWN = {"Origin": "http://127.0.0.1:8020"}


# ---------------------------------------------------------------------- content and words


def test_content_loads_and_refers_correctly():
    c = course.content()
    assert [lv["level"] for lv in c["levels"]] == [1, 2, 3]
    ladder = [e["song_id"] for e in course.ladder_entries()]
    assert ladder == ["mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle", "au-clair-de-la-lune", "frere-jacques",
                      "london-bridge", "ode-to-joy-left-hand", "twinkle-twinkle-left-hand", "frere-jacques-both-hands"]
    # PLAN 7.4 unlock table: the levels of the terms.
    levels = {t["id"]: t["level"] for t in c["terms"]}
    assert levels == {"finger_number": 1, "middle_c": 1, "hand_position": 1, "beat": 2, "rest": 2, "tempo": 2,
                      "bar": 3, "interval": 3, "sharp_flat": 4, "chord": 5, "major_minor": 5, "progression": 6,
                      "scale": 7}
    # Every term of Levels 1-3 has an unlock lesson in this version; Level 4+ terms stay locked.
    for t in c["terms"]:
        assert (t["unlocked_by"] is not None) == (t["level"] <= 3), t["id"]
    # Each skill moment: plain name, STE text, demo notes with fingers, a pass rule of 3 tries.
    for s in c["skills"].values():
        assert s["tries"] == 3 and s["name"] and s["text"] and s["steps"]
        assert all(n.get("finger") in (1, 2, 3, 4, 5) for n in s["demo"]["notes"])
        assert s["demo"]["hand_positions"]
        lv = next(e["level"] for e in course.ladder_entries() if any(k["id"] == s["id"] for k in e["skills"]))
        assert lv == s["level"], s["id"]
    # The demo fingering is on the keys of the hand position (same rule as the songs).
    for s in c["skills"].values():
        pos = sorted(s["demo"]["hand_positions"], key=lambda p: p["start"])
        for n in s["demo"]["notes"]:
            p = [x for x in pos if x["hand"] == n["hand"] and x["start"] <= n["start"] + 1e-9][-1]
            assert songs.position_keys(p)[n["finger"] - 1] == n["pitch"], (s["id"], n)


def test_skill_moments_sit_on_real_song_notes():
    for e in course.ladder_entries():
        song = songs.get(e["song_id"])
        hands = set(e["hands"])
        starts = sorted({n["start"] for n in song["notes"] if n["hand"] in hands})
        for sk in e["skills"]:
            assert sk["at_beat"] in starts, (e["song_id"], sk)
            assert sk["resume_beat"] <= sk["at_beat"] and sk["resume_beat"] in starts + [0]
            skill = course.content()["skills"][sk["id"]]
            assert set(skill["hands"]) <= hands, sk["id"]


TERM_RE = {t["id"]: re.compile(rf"\b(?:{t['pattern']})\b", re.I) for t in course.content()["terms"]}


def test_rule_6_course_texts_use_no_locked_term():
    """PLAN 7.4 Rule 6: a Level-N text does not use a term with an unlock level above N, unless
    the text explains the term (its card, or the skill moment that unlocks it)."""
    texts = course.course_texts()
    assert len(texts) > 60
    levels = {t["id"]: t["level"] for t in course.content()["terms"]}
    bad = []
    for level, where, text in texts:
        text = course.shown_text(text)  # every term unlocked (the normal path)
        for tid, rx in TERM_RE.items():
            if rx.search(text) and levels[tid] > level and not course.explains(where, tid):
                bad.append((where, tid, text))
    assert not bad, bad


SAME_PLAIN = {t["id"] for t in course.content()["terms"] if t["plain"].lower() == t["term"].lower()}


def _can_show(where):
    """Cards of terms with no unlock lesson in this version never reach the page."""
    m = re.match(r"term (\w+) card", where)
    return not m or course.content()["terms_by_id"][m.group(1)]["unlocked_by"] is not None


def test_rule_6_locked_terms_use_plain_words_when_moments_are_skipped():
    """A term that is locked (its skill moment was skipped, or the user skipped a level) never
    reaches the page: every course text, rendered with NO term unlocked, has no term word except
    the term that the text itself explains. Then the same with each single term unlocked."""
    all_terms = [t["id"] for t in course.content()["terms"] if t["unlocked_by"]]
    bad = []
    for _level, where, text in course.course_texts():
        if not _can_show(where):
            continue
        explained = course.explained_terms(where)
        for unlocked in [set()] + [{x} for x in all_terms]:
            out = course.render_text(text, unlocked, explained)
            visible = course.TERM_MARK.sub("", out)  # an unlocked mark may show its term
            for tid, rx in TERM_RE.items():
                if tid in explained or tid in SAME_PLAIN or tid in unlocked:
                    continue
                if rx.search(visible):
                    bad.append((where, sorted(unlocked), tid, out))
    assert not bad, bad[:5]


def test_term_marks_render_for_the_page():
    text = "Lift your finger and count the rest like [[beat|a beat|one click]]."
    assert course.render_text(text, set()) == "Lift your finger and count the rest like one click."
    assert course.render_text(text, {"beat"}) == "Lift your finger and count the rest like [[beat|a beat]]."
    assert course.render_text("Count the [[beat|beats|clicks]].", set()) == "Count the clicks."
    assert course.render_text("[[beat|beats]]", set()) == "the clicks"  # plural form -> plain_plural
    assert course.render_text("[[middle_c|Middle C]] is here.", set()) == "The C in the middle is here."
    assert course.render_text("[[middle_c]] is here.", {"middle_c"}) == "[[middle_c|middle C]] is here."
    assert course.shown_text("A bar has [[beat|4 beats|4 clicks]].") == "A bar has 4 beats."
    # The plain words of "bar" do not use "part" (one word, one meaning: "Part N" = a song part).
    bar = course.content()["terms_by_id"]["bar"]
    assert "part" not in (bar["plain"] + bar["plain_plural"]).lower()


def test_course_api_sends_plain_words_for_skipped_moments(client):
    """Level 2 "pauses" moment, with "beat" locked (its moment skipped): plain word on the page."""
    c = client
    sk = c.get("/api/course/skills/pauses").json()
    joined = " ".join(sk["text"])
    assert "one click" in joined and not TERM_RE["beat"].search(joined.replace("[[", " ").replace("]]", " "))
    assert "rest" in joined  # the moment explains its own term
    c.riyaz["store"].unlock_term("beat")
    joined = " ".join(c.get("/api/course/skills/pauses").json()["text"])
    assert "[[beat|a beat]]" in joined
    st = c.get("/api/course").json()
    b2 = next(s for s in st["basics"]["steps"] if s["id"] == "b2")
    assert all("[[" not in t["text"] and "middle C" not in t["text"] for t in b2["tasks"])  # middle C locked


def test_rule_6_finds_a_locked_term():
    """The check itself: a Level 1 text with "beat" (Level 2) is found."""
    assert TERM_RE["beat"].search("Play on each beat.") and TERM_RE["bar"].search("Repeat bar 2.")
    assert not TERM_RE["rest"].search("Press the key.") and not TERM_RE["bar"].search("sidebar")


def test_course_texts_are_ste_sentences():
    for level, where, text in course.course_texts():
        text = course.shown_text(text)
        if where.endswith(" title") or where.endswith(" name"):
            assert text[0].isupper() and len(text.split()) <= 8, (where, text)
            continue
        assert text[0].isupper() and text.rstrip('"').endswith((".", ":")), (where, text)
        for sentence in re.split(r"(?<=[.:])\s+", text):
            # ASD-STE100: 20 words for instructions, 25 for descriptions.
            assert len(sentence.split()) <= 25, (where, sentence)


def test_level_titles_use_plain_words():
    """Level titles show before the level starts: no term of Level 2 or more."""
    for lv in course.content()["levels"]:
        for tid, rx in TERM_RE.items():
            if course.content()["terms_by_id"][tid]["level"] > 1:
                assert not rx.search(course.shown_text(lv["title"] + " " + lv["text"])), (lv["level"], tid)


# ---------------------------------------------------------------------- drills


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def drill_env():
    clk = Clock()
    events = []
    d = Drill(events.append, now=clk, vel_split=lambda: 64)
    return d, clk, events


def press(d, clk, pitch, vel=80, hold=0.05):
    d.on_midi({"type": "note_on", "pitch": pitch, "vel": vel, "t": clk.t})
    clk.t += hold
    d.on_midi({"type": "note_off", "pitch": pitch, "t": clk.t})
    clk.t += 0.05


def test_drill_collect_every_c():
    d, clk, events = drill_env()
    d.start({"kind": "collect", "pitches": [36, 48, 60, 72, 84, 96]})
    for p in (60, 61, 60, 48, 36, 72, 84):
        press(d, clk, p)
    assert d.state()["status"] == "active" and d.state()["wrong"] == 1
    assert d.state()["expect"] == {"any": [96]}
    press(d, clk, 96)
    assert d.state()["status"] == "passed"
    assert [e for e in events if e["type"] == "drill_wrong"][0]["reason"] == "wrong_key"


def test_drill_steps_tries_and_wrong_key_restarts_the_try():
    d, clk, _ = drill_env()
    passed = []
    d.start({"kind": "steps", "tries": 3, "steps": [{"any": [60]}, {"any": [62]}, {"any": [64]}]},
            on_pass=lambda spec, summary: passed.append(summary) or {"unlocked": ["x"]})
    for p in (60, 62, 64):
        press(d, clk, p)
    assert d.state()["tries_ok"] == 1 and d.state()["last"] == "try_ok"
    press(d, clk, 60)
    press(d, clk, 65)  # wrong: this try starts again
    st = d.state()
    assert st["step"] == 0 and st["tries_ok"] == 1 and st["wrong"] == 1 and st["last"] == "wrong_key"
    for _ in range(2):
        for p in (60, 62, 64):
            press(d, clk, p)
    st = d.state()
    assert st["status"] == "passed" and st["result"]["unlocked"] == ["x"] and passed[0]["fails"] == 1


def test_drill_hold_rest_velocity_and_keys_together():
    d, clk, events = drill_env()
    d.start({"kind": "steps", "steps": [{"any": [62], "hold": 1.0}, {"any": [60], "rest": 0.6},
                                        {"all": [48, 60]}, {"any": None, "vel": "soft"}, {"any": None, "vel": "loud"}]})
    press(d, clk, 62, hold=0.4)  # too short
    assert d.state()["step"] == 0 and d.state()["last"] == "too_short"
    press(d, clk, 62, hold=1.1)
    assert d.state()["step"] == 1
    press(d, clk, 60)  # only 0.05 s after the release: in the pause
    assert d.state()["last"] == "too_early" and d.state()["step"] == 1
    clk.t += 0.7
    press(d, clk, 60)
    assert d.state()["step"] == 2
    d.on_midi({"type": "note_on", "pitch": 48, "vel": 80, "t": clk.t})
    clk.t += 0.1
    d.on_midi({"type": "note_on", "pitch": 60, "vel": 80, "t": clk.t})
    d.on_midi({"type": "note_off", "pitch": 48, "t": clk.t})
    d.on_midi({"type": "note_off", "pitch": 60, "t": clk.t})
    assert d.state()["step"] == 3
    press(d, clk, 70, vel=110)
    assert d.state()["last"] == "too_loud"
    press(d, clk, 70, vel=30)
    press(d, clk, 70, vel=40)
    assert d.state()["last"] == "too_soft"
    press(d, clk, 70, vel=100)
    assert d.state()["status"] == "passed"
    reasons = [e["reason"] for e in events if e["type"] == "drill_wrong"]
    assert reasons == ["too_short", "too_early", "too_loud", "too_soft"]


def test_drill_find_the_key():
    d, clk, _ = drill_env()
    d.start({"kind": "find_key", "rounds": 5}, seed=3)
    names = []
    for _ in range(5):
        st = d.state()
        tgt = st["target"]
        names.append(tgt["name"])
        assert tgt["pitches"] == [p for p in range(36, 97) if p % 12 == tgt["pc"]]
        press(d, clk, (tgt["pc"] + 1) % 12 + 60 if (tgt["pc"] + 1) % 12 in (0, 2, 4, 5, 7, 9, 11) else 61)  # wrong
        clk.t += 0.5
        press(d, clk, tgt["pitches"][-1])  # any octave counts
    st = d.state()
    assert st["status"] == "passed" and len(st["times"]) == 5 and st["wrong"] == 5
    assert all(a != b for a, b in zip(names, names[1:]))  # never the same key twice in a row
    assert all(n in "CDEFGAB" for n in names)  # Level 1: white keys only (no sharp/flat names)


# ---------------------------------------------------------------------- server: course, skill moments, terms


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        c.app_ref = app
        c.riyaz = app.state.riyaz
        yield c


def keys(c, pitches, vel=80, hold=0.0):
    sink = c.riyaz["midi"].sink
    import time

    for p in pitches:
        ps = p if isinstance(p, (list, tuple)) else [p]
        for x in ps:
            sink({"type": "note_on", "pitch": x, "vel": vel, "t": time.perf_counter()})
        if hold:
            time.sleep(hold)
        for x in ps:
            sink({"type": "note_off", "pitch": x, "t": time.perf_counter()})


def play_drill(c, state):
    """Press what the drill expects until it passes (a fake player that knows the answer)."""
    import time

    for _ in range(200):
        st = c.get("/api/drill").json()
        if st["status"] != "active":
            return st
        exp = st["expect"]
        if exp.get("rest"):
            time.sleep(exp["rest"] + 0.05)
        vel = 30 if exp.get("vel") == "soft" else 110 if exp.get("vel") == "loud" else 80
        pitches = exp.get("all") or (exp.get("any") or [60])[:1]
        keys(c, [pitches if exp.get("all") else pitches[0]], vel=vel, hold=exp.get("hold", 0) + 0.02 if exp.get("hold") else 0)
    raise AssertionError("drill did not pass")


def test_basics_unlock_terms_and_card_shows_once(client):
    c = client
    st = c.get("/api/course").json()
    assert st["level"] == 1 and not st["basics"]["done"] and st["current_song"] == "mary-had-a-little-lamb"
    assert not any(t["unlocked"] for t in c.get("/api/course/terms").json()["terms"])
    locked = c.get("/api/course/terms").json()["terms"][0]
    assert "term" not in locked and "card" not in locked  # a locked term never reaches the page
    for task in course.basics_tasks():
        if "drill" in task:
            s = c.post("/api/drill/start", json={"source": "basics", "ref": task["id"]}, headers=OWN).json()
            assert play_drill(c, s)["status"] == "passed"
    st = c.get("/api/course").json()
    assert not st["basics"]["done"]  # the 10-note demo (practice) is still open
    # B3 demo: the practice engine ends -> the server marks the task.
    c.riyaz["practice"].sink({"type": "practice_end", "song_id": "basics-demo", "mode": "wait", "completed": True,
                              "hands": ["R"], "wrong": 0, "stops": 10, "accuracy": 100.0, "speed": 1.0, "section": None})
    c.riyaz["flush_results"]()  # the result is saved on the results thread
    assert c.get("/api/course").json()["basics"]["done"]
    terms = {t["id"]: t for t in c.get("/api/course/terms").json()["terms"]}
    assert terms["middle_c"]["unlocked"] and terms["finger_number"]["unlocked"]
    assert not terms["middle_c"]["seen"] and terms["middle_c"]["card"].startswith("Find the 2 black keys")
    assert c.post("/api/course/terms/middle_c/seen", headers=OWN).json() == {"ok": True}
    assert {t["id"]: t["seen"] for t in c.get("/api/course/terms").json()["terms"]}["middle_c"] is True
    assert c.post("/api/course/terms/tempo/seen", headers=OWN).status_code == 404


def test_skill_moment_in_a_song_unlocks_its_term(client):
    """PLAN 8.2: the song stops before the new skill; 3 tries; the song goes on from just before."""
    c = client
    moments = c.get("/api/course/moments/mary-had-a-little-lamb").json()["moments"]
    assert [m["id"] for m in moments] == ["five_finger", "repeat_key"]
    s = c.post("/api/drill/start", json={"source": "skill", "ref": "five_finger"}, headers=OWN).json()
    assert s["tries"] == 3 and s["expect"]["any"] == [60]
    st = play_drill(c, s)
    assert st["result"]["unlocked"] == ["hand_position"] and st["result"]["new"] is True
    assert [m["id"] for m in c.get("/api/course/moments/mary-had-a-little-lamb").json()["moments"]] == ["repeat_key"]
    assert "five_finger" in c.get("/api/course").json()["skills_done"]
    # Again: no new unlock.
    s = c.post("/api/drill/start", json={"source": "skill", "ref": "five_finger"}, headers=OWN).json()
    assert play_drill(c, s)["result"]["unlocked"] == []
    a = c.riyaz["store"].attempts(kind="drill")
    assert a[0]["item"] == "skill:five_finger" and len(a) == 2


def test_practice_break_and_seek():
    """The practice engine stops before the new skill and goes on from the resume beat."""
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    song = songs.get("mary-had-a-little-lamb")
    p.start(song, mode="wait", hands=["R"], count_in=False, speed=1.0,
            breaks=[{"beat": 4, "skill": "repeat_key"}, {"beat": 0, "skill": "five_finger"}])
    assert p.breaks == [(4.0, "repeat_key")]  # a skill at the start is shown before the song
    for _ in range(4000):
        clk.t += 0.01
        p.tick()
        st = p.state()
        if st["paused"]:
            break
        if st["waiting"]:
            for e in st["expected"]:
                p.on_midi({"type": "note_on", "pitch": e["pitch"], "t": clk.t})
                p.on_midi({"type": "note_off", "pitch": e["pitch"], "t": clk.t})
    sk = [e for e in events if e["type"] == "practice_skill"]
    assert sk and sk[0]["skill"] == "repeat_key" and sk[0]["beat"] == 4.0
    st = p.state()
    assert st["pause_reason"] == "skill" and st["stop_index"] == 4 and 3.5 <= st["beat"] < 4
    st = p.seek(2.0, run=st["run"])
    assert st["running"] and st["stop_index"] == 2 and st["anchor_beat"] == pytest.approx(1.0)
    assert p.seek(2.0, run=999)["stop_index"] == 2  # an old run changes nothing


def test_practice_end_has_accuracy():
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    song = songs.get("ode-to-joy")
    p.start(song, mode="wait", hands=["R"], count_in=False)
    wrong_at = {0, 5, 9}
    done = set()
    for _ in range(100000):
        clk.t += 0.01
        p.tick()
        st = p.state()
        if st["done"]:
            break
        if st["waiting"] and st["stop_index"] not in done:
            done.add(st["stop_index"])
            if st["stop_index"] in wrong_at:
                p.on_midi({"type": "note_on", "pitch": 90, "t": clk.t})
                p.on_midi({"type": "note_off", "pitch": 90, "t": clk.t})
            for e in st["expected"]:
                p.on_midi({"type": "note_on", "pitch": e["pitch"], "t": clk.t})
                p.on_midi({"type": "note_off", "pitch": e["pitch"], "t": clk.t})
    end = [e for e in events if e["type"] == "practice_end"][0]
    assert end["stops"] == 30 and end["clean_stops"] == 27 and end["accuracy"] == 90.0
    assert end["section"] is None and len(end["errors"]) == 3 and end["errors"][0]["beat"] == 0.0


def run_evt(song_id, hands, accuracy=100.0, speed=1.0, section=None):
    return {"type": "practice_end", "song_id": song_id, "mode": "wait", "completed": True, "hands": hands, "wrong": 0,
            "stops": 30, "accuracy": accuracy, "speed": speed, "section": section, "seconds": 20.0,
            "errors": [{"beat": 17.0, "pitch": 70}] if accuracy < 100 else []}


def test_song_done_rule():
    ok = run_evt("x", ["R"], 80.0)
    assert song_done(ok, ["R"])
    assert not song_done({**ok, "accuracy": 79.9}, ["R"])
    assert not song_done({**ok, "speed": 0.95}, ["R"])
    assert not song_done({**ok, "section": 0}, ["R"])
    assert not song_done({**ok, "mode": "watch"}, ["R"])
    assert not song_done(ok, ["R", "L"])
    assert song_done({**ok, "hands": ["R", "L"]}, ["R"])


def test_level_1_to_2_to_3_and_bar_lines_only_at_level_3(client):
    """PLAN 8.3: songs done -> level done -> next level. Rule 5: bar lines from Level 3."""
    c = client
    sink = c.riyaz["practice"].sink
    events = []
    c.riyaz["practice"].sink = lambda e: (events.append(e), sink(e))  # noqa: E731 (see the course events)
    hub = c.app_ref.state.hub
    published = []
    orig = hub.publish
    hub.publish = lambda e: (published.append(e), orig(e))

    def run(sid, hands, **kw):
        c.riyaz["practice"].sink(run_evt(sid, hands, **kw))
        c.riyaz["flush_results"]()  # the result is saved on the results thread
        return [e for e in published if e.get("type") == "course"][-1]

    st = c.get("/api/course").json()
    assert st["level"] == 1 and st["bar_lines"] is False
    r = run("mary-had-a-little-lamb", ["R"], accuracy=75.0)
    assert not r["done"] and not r["level_up"]
    r = run("mary-had-a-little-lamb", ["R"], speed=0.8)
    assert not r["done"]
    r = run("mary-had-a-little-lamb", ["R"], accuracy=85.0)
    assert r["done"] and r["newly_done"] and not r["level_up"]
    run("ode-to-joy", ["R"])
    assert c.get("/api/course").json()["current_song"] == "twinkle-twinkle"
    r = run("twinkle-twinkle", ["R"])
    assert r["level_up"] and r["level_before"] == 1 and r["level"] == 2
    st = c.get("/api/course").json()
    assert st["level"] == 2 and st["levels"][0]["done"] and st["bar_lines"] is False
    # Imported-song cards use the real level now (not a setting).
    assert c.get("/api/songs").json()["user_level"] == 2
    for sid in ("au-clair-de-la-lune", "frere-jacques", "london-bridge"):
        r = run(sid, ["R"])
    assert r["level_up"] and r["level"] == 3
    st = c.get("/api/course").json()
    assert st["level"] == 3 and st["bar_lines"] is True and st["current_song"] == "ode-to-joy-left-hand"
    r = run("frere-jacques-both-hands", ["R"])  # one hand only: not done
    assert not r["done"] and r["required_hands"] == ["R", "L"]
    run("ode-to-joy-left-hand", ["L"])
    run("twinkle-twinkle-left-hand", ["L"])
    r = run("frere-jacques-both-hands", ["R", "L"])
    assert r["level_up"] and r["level"] == 4
    st = c.get("/api/course").json()
    assert st["all_done"] and st["user_level"] == 3 and all(lv["done"] for lv in st["levels"])
    # The errors per part are kept (for "the hardest part first").
    prog = c.riyaz["store"].song_progress("mary-had-a-little-lamb")["mary-had-a-little-lamb"]
    assert prog["part_errors"]["1"] == [1, 0, 1] and prog["runs"] == 3


def test_skip_forward_warns_and_sets_the_level(client):
    c = client
    info = c.get("/api/course/skip/3").json()
    assert info["basics"] is True and "Stay where your hand sits" in info["needed"] and "Keep the same speed" in info["needed"]
    assert c.post("/api/course/skip", json={"level": 3}, headers={"Origin": "http://evil.example"}).status_code == 403
    r = c.post("/api/course/skip", json={"level": 3}, headers=OWN).json()
    assert r["now"] == 3
    st = c.get("/api/course").json()
    assert st["level"] == 3 and st["bar_lines"] and st["levels"][2]["open"] and st["levels"][1]["open"]
    assert c.post("/api/course/skip", json={"level": 9}, headers=OWN).status_code == 400
    # Level 3 terms stay locked until their skill moment.
    assert not {t["id"]: t for t in c.get("/api/course/terms").json()["terms"]}["bar"]["unlocked"]


def test_new_post_routes_need_own_origin(client):
    bad = {"Origin": "http://evil.example"}
    for path, body in (("/api/drill/start", {"source": "find_key"}), ("/api/drill/stop", {}),
                       ("/api/session/start", {}), ("/api/settings/habit", {"goal_minutes": 10}),
                       ("/api/habit/notify-test", {}), ("/api/practice/seek", {"beat": 0}),
                       ("/api/course/terms/beat/seen", {}), ("/api/course/skip", {"level": 2}),
                       ("/api/session/1/block", {"index": 0, "status": "active"}), ("/api/session/1/end", {})):
        assert client.post(path, json=body, headers=bad).status_code == 403, path
    assert client.get("/api/today", headers={"Host": "evil.example"}).status_code == 400
    # Nothing changed: no session was made, the level floor is the same.
    assert client.get("/api/today").json()["session"] is None
    assert client.get("/api/course").json()["level_floor"] == 1


def test_phase_2_database_opens_with_the_new_store(data_dir, tmp_path):
    """A Phase 1-2 database (settings table only, no user_version) opens; settings stay."""
    import json
    import sqlite3

    from riyaz import db

    path = tmp_path / "phase2.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT INTO settings VALUES (?, ?)", ("midi.port", json.dumps("USB MIDI Interface")))
    conn.execute("INSERT INTO settings VALUES (?, ?)", ("practice.options", json.dumps({"speed": 0.8})))
    conn.commit()
    conn.close()
    store = Store(path)
    assert store.schema_version() == db.SCHEMA_VERSION
    assert store.get("midi.port") == "USB MIDI Interface" and store.get("practice.options") == {"speed": 0.8}
    tables = {r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"days", "sessions", "attempts", "song_progress", "course", "skills_done", "terms"} <= tables
    sid = store.add_session("2026-11-13", 15, {"blocks": []})
    assert store.session(sid)["day"] == "2026-11-13"
    store.close()
    again = Store(path)  # open again: no change, no error
    assert again.schema_version() == db.SCHEMA_VERSION and again.get("midi.port") == "USB MIDI Interface"
    again.close()
    # A database of a newer app opens too (tables are only added).
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    newer = Store(path)
    assert newer.schema_version() == db.SCHEMA_VERSION + 1 and newer.get("midi.port") == "USB MIDI Interface"
    newer.close()


def test_drill_start_errors(client):
    c = client
    assert c.post("/api/drill/start", json={"source": "skill", "ref": "nope"}).status_code == 404
    assert c.post("/api/drill/start", json={"source": "basics", "ref": "b3-demo"}).status_code == 404
    assert c.post("/api/drill/start", json={"source": "x"}).status_code == 400
    assert c.post("/api/drill/start", json={"source": "session", "session_id": 99, "block": 0}).status_code == 404


# ---------------------------------------------------------------------- daily session


def test_block_minutes_for_each_length():
    for total, want in ((10, {"warmup": 1.0, "song": 6.0, "review": 1.5, "intuition": 1.5}),
                        (15, {"warmup": 1.5, "song": 9.5, "review": 2.0, "intuition": 2.0}),
                        (20, {"warmup": 2.0, "song": 12.0, "review": 3.0, "intuition": 3.0}),
                        (30, {"warmup": 3.0, "song": 18.0, "review": 4.5, "intuition": 4.5})):
        got = block_minutes(total)
        assert got == want and sum(got.values()) == total


def test_plan_uses_error_data_and_done_songs(store):
    c = Course(store)
    p = plan(store, c)
    assert [b["kind"] for b in p["blocks"]] == ["warmup", "song", "review", "intuition"]
    assert p["minutes"] == 20 and p["blocks"][1]["song_id"] == "mary-had-a-little-lamb"
    assert [s["label"] for s in p["blocks"][1]["steps"]] == ["whole"]  # no error data yet
    assert p["blocks"][2]["why"] == "current_song" and p["blocks"][3]["drill"]["kind"] == "find_key"
    assert len(p["blocks"][0]["drill"]["steps"]) == config.WARMUP_NOTES
    c.record_run(run_evt("mary-had-a-little-lamb", ["R"], accuracy=90.0))  # done, errors in Part 2
    c.record_run(run_evt("ode-to-joy", ["R"], accuracy=70.0))  # not done, 1 error in Part 2 (beat 17)
    p = plan(store, c, minutes=10)
    song = p["blocks"][1]
    assert p["minutes"] == 10 and song["song_id"] == "ode-to-joy" and song["hard_part"] == 1
    assert [(s["section"], s["label"]) for s in song["steps"]] == [(1, "hard_part"), (None, "whole")]
    assert p["blocks"][0]["pattern"]["why"] == "hard_part" and p["blocks"][0]["pattern"]["from_beat"] == 16
    review = p["blocks"][2]
    assert review["song_id"] == "mary-had-a-little-lamb" and review["why"] == "done_song" and review["section"] == 1


def test_warmup_pattern_uses_the_first_hand_move():
    twinkle = songs.get("twinkle-twinkle")
    w = warmup_pattern(twinkle, ["R"], None, 5)
    assert w["why"] == "hand_move" and [s["any"][0] for s in w["steps"]] == [60, 60, 67, 67, 69]
    both = songs.get("frere-jacques-both-hands")
    w = warmup_pattern(both, ["R", "L"], 0, 3)
    assert w["why"] == "hard_part"
    assert w["steps"][0] == {"all": [48, 60], "fingers": {"48": 1, "60": 1}, "hand": "RL"}


def test_daily_session_end_to_end_with_fake_keys(client):
    """PLAN Phase 3 acceptance 3 (backend part): a whole session with keys into the server sink.
    The CoreMIDI run with tools/fake_player.py --session is in PROGRESS.md."""
    import time

    c = client
    today = c.get("/api/today").json()
    assert today["session"] is None and today["habit"]["streak"]["days"] == 0
    s = c.post("/api/session/start", json={"minutes": 10}, headers=OWN).json()
    sid = s["id"]
    assert s["plan"]["minutes"] == 10 and [b["status"] for b in s["blocks"]] == ["todo"] * 4
    # 1. Warm-up drill
    st = c.post("/api/drill/start", json={"source": "session", "session_id": sid, "block": 0}, headers=OWN).json()
    assert play_drill(c, st)["status"] == "passed"
    c.post(f"/api/session/{sid}/block", json={"index": 0, "status": "done", "seconds": 60}, headers=OWN)
    # 2. Song: wait mode in the real practice engine (threaded clock), with a skill moment break.
    song = s["plan"]["blocks"][1]
    moments = c.get(f"/api/course/moments/{song['song_id']}").json()["moments"]
    first = moments[0]
    assert first["at_beat"] == 0  # shown before the song starts
    assert play_drill(c, c.post("/api/drill/start", json={"source": "skill", "ref": first["id"]}).json())["status"] == "passed"
    later = moments[1]
    st = c.post("/api/practice/start", json={"song_id": song["song_id"], "mode": "wait", "hands": song["hands"],
                                             "speed": 1.5, "count_in": False, "accompany": False,
                                             "breaks": [{"beat": later["at_beat"], "skill": later["id"]}]}).json()
    run = st["run"]
    seen_skill = False
    done = set()
    t0 = time.time()
    while time.time() - t0 < 30:
        st = c.get("/api/practice").json()
        if st["done"]:
            break
        if st["paused"] and st["pause_reason"] == "skill":
            seen_skill = True
            assert play_drill(c, c.post("/api/drill/start", json={"source": "skill", "ref": later["id"]}).json())["status"] == "passed"
            c.post("/api/practice/seek", json={"beat": later["resume_beat"], "run": run})
            done = {x for x in done if x[1] < st["stop_index"] - 2}  # the song goes back: these stops come again
            continue
        if st["waiting"] and (st["run"], st["stop_index"]) not in done:
            done.add((st["run"], st["stop_index"]))
            keys(c, [e["pitch"] for e in st["expected"]])
        time.sleep(0.01)
    assert st["done"] and seen_skill, st
    time.sleep(0.1)
    prog = c.riyaz["store"].song_progress(song["song_id"])[song["song_id"]]
    assert prog["done"] is True  # whole song, no wrong key, speed 150% (>= 100%)
    c.post(f"/api/session/{sid}/block", json={"index": 1, "status": "done", "seconds": 300}, headers=OWN)
    # 3. Review: skipped. 4. Find the key.
    c.post(f"/api/session/{sid}/block", json={"index": 2, "status": "skipped"}, headers=OWN)
    st = c.post("/api/drill/start", json={"source": "session", "session_id": sid, "block": 3}, headers=OWN).json()
    assert st["kind"] == "find_key" and play_drill(c, st)["status"] == "passed"
    c.post(f"/api/session/{sid}/block", json={"index": 3, "status": "done", "seconds": 90}, headers=OWN)
    end = c.post(f"/api/session/{sid}/end", headers=OWN).json()
    summ = end["summary"]
    assert end["ended"] and summ["blocks_done"] == 3 and summ["blocks_skipped"] == 1
    assert set(summ["new_skills"]) == {"Stay where your hand sits", "Press the same key again"}
    assert summ["best"]["song_id"] == song["song_id"] and summ["best"]["accuracy"] == 100.0
    assert summ["streak"] == 1 and summ["find_key_seconds"] is not None
    h = c.get("/api/habit").json()
    assert h["streak"]["days"] == 1 and h["streak"]["today_done"]
    assert c.post(f"/api/session/{sid}/block", json={"index": 0, "status": "done"}).status_code == 400
    assert c.get("/api/today").json()["finished"][0]["id"] == sid


def test_song_done_needs_100_percent_not_more():
    """The rule is "100% speed": faster also counts (speed >= 100%)."""
    assert song_done(run_evt("x", ["R"], speed=1.5), ["R"])


# ---------------------------------------------------------------------- streak, calendar, practice time


def days(*specs):
    """'2026-11-02' (practice) or ('2026-11-02', seconds, sessions)."""
    out = {}
    for s in specs:
        d, sec, n = (s, 600, 0) if isinstance(s, str) else s
        out[d] = {"seconds": sec, "sessions": n}
    return out


def test_streak_counts_days_in_a_row():
    # Monday 2026-11-09 .. Friday 2026-11-13
    assert streak(days("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"), "2026-11-13")["days"] == 4
    # Today not yet: the streak runs to yesterday.
    st = streak(days("2026-11-11", "2026-11-12"), "2026-11-13")
    assert st["days"] == 2 and not st["today_done"]
    # A finished session counts; 30 s of keys does not.
    assert streak(days(("2026-11-13", 0, 1)), "2026-11-13")["days"] == 1
    assert streak(days(("2026-11-13", 30, 0)), "2026-11-13")["days"] == 0
    assert streak({}, "2026-11-13") == {"days": 0, "frozen": [], "freeze_left": True, "today_done": False}


def test_streak_freeze_one_day_each_week():
    # Missed Wednesday 11-11: the freeze covers it. A frozen day does not add to the count.
    st = streak(days("2026-11-09", "2026-11-10", "2026-11-12", "2026-11-13"), "2026-11-13")
    assert st["days"] == 4 and st["frozen"] == ["2026-11-11"] and st["freeze_left"] is False
    # 2 missed days in a row: the streak breaks.
    assert streak(days("2026-11-09", "2026-11-12", "2026-11-13"), "2026-11-13")["days"] == 2
    # 2 missed days in the same week: only one freeze.
    assert streak(days("2026-11-09", "2026-11-11", "2026-11-13"), "2026-11-13")["days"] == 2
    # One missed day in each of 2 weeks: both are covered.
    st = streak(days("2026-11-03", "2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08", "2026-11-09",
                     "2026-11-11", "2026-11-12", "2026-11-13"), "2026-11-13")
    assert st["days"] == 9 and st["frozen"] == ["2026-11-04", "2026-11-10"]
    # Yesterday missed, today not yet: the streak is still alive (the user can practice today).
    st = streak(days("2026-11-10", "2026-11-11"), "2026-11-13")
    assert st["days"] == 2 and st["frozen"] == ["2026-11-12"]
    # A missed day long ago (a gap of 2 days) does not count.
    assert streak(days("2026-11-01", "2026-11-04", "2026-11-05"), "2026-11-05")["days"] == 2


def test_calendar_heat_map():
    cal = calendar(days(("2026-11-13", 1300, 1), ("2026-11-12", 400, 0), ("2026-11-10", 100, 0)), "2026-11-13", 20, weeks=2)
    cells = {c["day"]: c for c in cal["cells"]}
    assert cal["start"] == "2026-11-02" and len(cal["cells"]) == 14  # Monday first, whole weeks
    assert cells["2026-11-13"]["level"] == 3 and cells["2026-11-12"]["level"] == 1 and cells["2026-11-10"]["level"] == 1
    assert cells["2026-11-11"]["frozen"] and cells["2026-11-15"]["future"] and cells["2026-11-09"]["level"] == 0


def test_activity_counts_time_between_key_presses(store):
    clk = Clock(1000.0)
    a = Activity(store, now=clk, day=lambda: "2026-11-13", gap=60)
    for t in (1000, 1005, 1010, 1100, 1102):  # 5 + 5, then a 90 s break, then 2
        clk.t = t
        a.press(t)
    a.flush()
    assert store.day_seconds("2026-11-13") == pytest.approx(12)


def test_reminder_once_a_day_after_the_time_and_below_the_goal(store):
    sent = []
    now = [dt.datetime(2026, 11, 13, 18, 59)]
    a = Activity(store, day=lambda: "2026-11-13")
    r = Reminder(store, a, notify=lambda text: sent.append(text) or True, now=lambda: now[0])
    assert r.check() is False  # off by default
    store.set("habit", {"notify": True, "notify_time": "19:00", "goal_minutes": 10})
    assert r.check() is False  # before the time
    now[0] = dt.datetime(2026, 11, 13, 19, 1)
    assert r.check() is True and sent == ["Time for your Riyaz."]
    assert r.check() is False  # once a day
    now[0] = dt.datetime(2026, 11, 14, 19, 5)
    store.add_seconds("2026-11-14", 600)
    assert r.check() is False  # goal reached
    now[0] = dt.datetime(2026, 11, 15, 20, 0)
    assert r.check() is True and len(sent) == 2


def test_habit_settings(client):
    c = client
    assert c.get("/api/settings/habit").json() == {"session_minutes": 20, "goal_minutes": 20, "notify": False,
                                                   "notify_time": "19:00", "song_id": None}
    r = c.post("/api/settings/habit", json={"session_minutes": 15, "goal_minutes": 12, "notify": "yes",
                                           "notify_time": "25:00", "song_id": "ode-to-joy"}).json()
    assert r == {"session_minutes": 15, "goal_minutes": 20, "notify": False, "notify_time": "19:00", "song_id": "ode-to-joy"}
    assert c.get("/api/today").json()["plan"]["minutes"] == 15
    assert c.get("/api/today").json()["plan"]["blocks"][1]["song_id"] == "ode-to-joy"
    r = c.post("/api/settings/habit", json={"notify": True, "notify_time": "07:30", "song_id": "nope"}).json()
    assert r["notify"] and r["notify_time"] == "07:30" and r["song_id"] is None


# ------------------------------------------------------------------ Phase 3 review fixes


def test_run_result_is_saved_off_the_practice_lock(client, monkeypatch):
    """The practice_end handler (database writes, course) must not run inside Practice._lock."""
    import threading

    c = client
    pr = c.riyaz["practice"]
    go = threading.Event()
    seen = []
    orig = Course.record_run

    def spy(self, *a, **kw):
        go.wait(5)
        seen.append(threading.current_thread().name)
        assert pr._lock.acquire(timeout=2)  # the lock is free while the result is saved
        pr._lock.release()
        return orig(self, *a, **kw)

    monkeypatch.setattr(Course, "record_run", spy)
    with pr._lock:  # Practice emits practice_end with its lock held
        pr.sink(run_evt("mary-had-a-little-lamb", ["R"]))
        returned_first = not seen  # the sink did not wait for the handler
    go.set()
    c.riyaz["flush_results"]()
    assert returned_first and seen and seen[0].startswith("riyaz-results")
    assert c.riyaz["store"].song_progress("mary-had-a-little-lamb")["mary-had-a-little-lamb"]["done"]


def test_song_list_is_cached_until_a_file_changes(data_dir):
    a = songs.load_all()
    b = songs.load_all()
    assert a == b and a is not b and all(a[k] is b[k] for k in a)  # same songs, read one time
    folder = config.user_songs_path()
    folder.mkdir(parents=True, exist_ok=True)
    extra = dict(songs.get("mary-had-a-little-lamb"))
    extra = {k: v for k, v in extra.items() if k != "end"}
    extra["id"], extra["title"] = "my-test-song", "My test song"
    import json

    (folder / "my-test-song.json").write_text(json.dumps(extra))
    assert "my-test-song" in songs.load_all()  # a new file is seen without invalidate()
    (folder / "my-test-song.json").unlink()
    assert "my-test-song" not in songs.load_all()


_LETTERS = {0: "C", 2: "D", 4: "E", 5: "F", 7: "G", 9: "A", 11: "B"}


def _letter(pitch):
    return _LETTERS.get(pitch % 12)


def _white_steps(a, b):
    """White keys from a (not counted) to b (counted)."""
    lo, hi = sorted((a, b))
    return sum(1 for p in range(lo, hi + 1) if p != a and _letter(p))


def _position_texts():
    """(sentences, {hand: [positions]}) for each skill moment and basics task."""
    c = course.content()
    out = []
    for sk in c["skills"].values():
        pos = {}
        for p in sk["demo"]["hand_positions"]:
            pos.setdefault(p["hand"], []).append(p)
        out.append((sk["id"], sk["text"], pos))
    for t in course.basics_tasks():
        if t.get("hand"):
            out.append((t["id"], [t["text"]], {t["hand"]["hand"]: [t["hand"]]}))
    return out


def test_position_texts_match_the_hand_positions():
    """Texts that name a key for a finger agree with the hand position (MIDI numbers).

    Review finding: "the G just left of middle C" was G3 (55), but the key just left of middle C
    is B. G3 is 3 white keys to the left of middle C.
    """
    checked = 0
    for ref, texts, pos in _position_texts():
        sentences = [x.strip() for t in texts for x in re.split(r"(?<=\.)\s+", course.shown_text(t)) if x.strip()]
        hand = None
        named = None  # pitch of the key that the last sentence named
        for s in sentences:
            m = re.search(r"\b(right|left) (thumb|little finger) on (?:the )?(middle C|[A-G])\b( left of middle C)?", s)
            if m:
                hand = "R" if m.group(1) == "right" else "L"
                keys = songs.position_keys(pos[hand][0])
                key = keys[0] if m.group(2) == "thumb" else keys[4]
                if m.group(3) == "middle C":
                    assert key == 60, (ref, s)
                else:
                    assert _letter(key) == m.group(3), (ref, s, key)
                if m.group(4):  # "the C left of middle C" = the next C down
                    assert key == 48, (ref, s)
                named = key
                checked += 1
            m = re.search(r"\b([A-G]) just (left|right) of middle C", s)
            if m:
                want = 59 if m.group(2) == "left" else 62
                assert _letter(want) == m.group(1), (ref, s)
                checked += 1
            m = re.search(r"\bThis ([A-G]) is (\d+) white keys? to the (left|right) of middle C", s)
            if m:
                assert named is not None and _letter(named) == m.group(1), (ref, s)
                assert (named < 60) == (m.group(3) == "left") and _white_steps(60, named) == int(m.group(2)), (ref, s, named)
                checked += 1
            m = re.search(r"\bmove your thumb to ([A-G])\b", s, re.I)
            if m:
                hand = hand or next(iter(pos))
                assert _letter(pos[hand][-1]["thumb_pitch"]) == m.group(1), (ref, s)
                checked += 1
            m = re.search(r"\bfinger (\d) is on ([A-G])\b", s)
            if m:
                hand = hand or next(iter(pos))
                assert _letter(songs.position_keys(pos[hand][-1])[int(m.group(1)) - 1]) == m.group(2), (ref, s)
                checked += 1
            m = re.search(r"\bPlay ((?:[A-G], )*[A-G]) with fingers ((?:\d, )*\d)\b", s)
            if m:
                h = hand or next(iter(pos))
                letters = m.group(1).split(", ")
                fingers = [int(x) for x in m.group(2).split(", ")]
                assert len(letters) == len(fingers), (ref, s)
                for letter, f in zip(letters, fingers):
                    assert any(_letter(songs.position_keys(p)[f - 1]) == letter for p in pos[h]), (ref, s, letter, f)
                checked += 1
    assert checked >= 6  # the check found the position texts (not an empty test)


def _session_env(store, day, clk):
    c = Course(store, now=clk)
    a = Activity(store, now=clk, day=lambda: day[0], gap=60)
    return Sessions(store, c, a, now=clk, day=lambda: day[0]), a


def test_open_session_of_an_earlier_day_is_closed(store):
    """B3: a session left open at midnight (or when the app closed) is closed on the next day;
    practice time after midnight goes to today's row, not to the old session."""
    day = ["2026-11-12"]
    clk = Clock(1_000_000.0)
    ses, act = _session_env(store, day, clk)
    s = ses.start(10)
    ses.block(s["id"], 0, "active")
    for t in (0, 10, 20):  # 20 s of practice in the session
        clk.t = 1_000_000.0 + t
        act.press(clk.t)
    ses.block(s["id"], 0, "done", seconds=30)
    act.flush()
    assert store.session(s["id"])["seconds"] == pytest.approx(20)
    # Midnight: the user plays on, the page has not asked for /api/today yet.
    day[0] = "2026-11-13"
    for t in (30, 40):
        clk.t = 1_000_000.0 + t
        act.press(clk.t)
    act.flush()
    assert store.session(s["id"])["seconds"] == pytest.approx(20)  # not added to yesterday's session
    assert store.day_seconds("2026-11-13") == pytest.approx(20)  # the gap over midnight counts for the new day
    clk.t += 3600
    t = ses.today()
    assert t["session"] is None and ses.active_id is None
    old = store.session(s["id"])
    assert old["ended"] is not None and old["summary"] is not None
    assert old["ended"] < clk.t - 3000  # ended at its last activity, not now
    assert store.all_days()["2026-11-12"]["sessions"] == 1  # one part was done
    new = ses.start(10)
    assert new["day"] == "2026-11-13" and ses.active_id == new["id"]


def test_old_session_closed_at_start_too(store):
    day = ["2026-11-10"]
    clk = Clock(2_000_000.0)
    ses, _ = _session_env(store, day, clk)
    s = ses.start(10)  # no part done
    day[0] = "2026-11-13"
    new = ses.start(15)
    old = store.session(s["id"])
    assert old["ended"] is not None and old["summary"]["blocks_done"] == 0
    assert store.all_days().get("2026-11-10", {"sessions": 0})["sessions"] == 0
    assert ses.today()["session"]["id"] == new["id"]


def test_block_keeps_start_time_and_hidden_time(store):
    """B4: the page gets the block start time (server time) and the hidden seconds after a reload."""
    day = ["2026-11-13"]
    clk = Clock(3_000_000.0)
    ses, _ = _session_env(store, day, clk)
    s = ses.start(10)
    ses.block(s["id"], 0, "active")
    clk.t += 50
    ses.block(s["id"], 0, "active", paused=12.5)  # the page was hidden for 12.5 s
    b = ses.today()["session"]["blocks"][0]
    assert b["started"] == 3_000_000.0 and b["paused"] == 12.5 and b["status"] == "active"


def test_time_before_a_session_does_not_count_for_the_session(store):
    """Found in the acceptance run: session practice time (58 s) was more than its wall time (46 s),
    because the gap from the last key press before the start went to the session."""
    clk = Clock(5000.0)
    a = Activity(store, now=clk, day=lambda: "2026-11-13", gap=60)
    a.press(5000.0)
    clk.t = 5010.0
    sid = store.add_session("2026-11-13", 10, {"blocks": []}, 5010.0)
    a.set_session(sid, "2026-11-13")
    for t in (5015.0, 5020.0):
        clk.t = t
        a.press(t)
    a.flush()
    assert store.session(sid)["seconds"] == pytest.approx(10)  # 5010-5020 only
    assert store.day_seconds("2026-11-13") == pytest.approx(20)  # the day has all of it
