"""Phase 4: play-along matcher and scores, live tips, findings, automatic adapt, spaced repetition,
skill model (PLAN 6.4, 7.1-7.3, 9.3, 9.4). Fake clock, no CoreMIDI."""

import re
import sqlite3

import pytest

from riyaz import config, course, feedback, review, skills, songs
from riyaz.db import Store
from riyaz.matcher import PlayMatcher, score_of
from riyaz.practice import Practice
from fastapi.testclient import TestClient

from riyaz.server import create_app
from tools.fake_player import play_plan, timed_events

BUILTIN = ["mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle", "au-clair-de-la-lune", "frere-jacques",
           "london-bridge", "ode-to-joy-left-hand", "twinkle-twinkle-left-hand", "frere-jacques-both-hands"]


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        c.app_ref = app
        c.riyaz = app.state.riyaz
        yield c


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def simulate(song, hands, plan_kw=None, speed=1.0, section=None, span=None, loop=None, tick=0.005, extra_s=1.0):
    """A play-along run with a fake clock: key events from fake_player.play_plan."""
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    st = p.start(song, mode="play", hands=hands, speed=speed, count_in=True, accompany=False, section=section,
                 span=span, loop=loop)
    plan = play_plan(song, hands, start=st["range"][0], end=st["range"][1], **(plan_kw or {}))
    at, ab, rate = st["anchor_t"], st["anchor_beat"], st["rate"]
    keys = timed_events(plan, lambda b: at + (b - ab) / rate)
    end_t = at + (st["range"][1] - ab) / rate + extra_s
    i = 0
    while clk.t < end_t and not p.state()["done"]:
        while i < len(keys) and keys[i][0] <= clk.t:
            t, on, pitch, vel = keys[i]
            p.on_midi({"type": "note_on" if on else "note_off", "pitch": pitch, "velocity": vel, "t": t})
            i += 1
        p.tick(clk.t)
        clk.t += tick
    return p, events, plan


def of(events, kind):
    return [e for e in events if e["type"] == kind]


# ---------------------------------------------------------------------- matcher (PLAN 6.4)

NOTES = [{"id": i, "pitch": p, "start": float(i), "dur": 1.0, "hand": "R", "finger": f, "vel": 80}
         for i, (p, f) in enumerate([(60, 1), (62, 2), (64, 3), (65, 4), (67, 5), (65, 4), (64, 3), (62, 2)])]
SONG = {"id": "t", "title": "T", "bpm": 60, "time_signature": [4, 4], "end": 8.0, "notes": NOTES,
        "sections": [{"name": "Part 1", "start": 0.0, "end": 4.0}, {"name": "Part 2", "start": 4.0, "end": 8.0}],
        "hand_positions": [{"hand": "R", "start": 0, "thumb_pitch": 60}]}


def test_same_key_twice_late_press_takes_the_first_note():
    song = {**SONG, "notes": [{"id": 0, "pitch": 62, "start": 0.0, "dur": 0.5, "hand": "R", "finger": 2, "vel": 80},
                              {"id": 1, "pitch": 62, "start": 0.5, "dur": 0.5, "hand": "R", "finger": 2, "vel": 80}]}
    m = PlayMatcher.for_song(song, ["R"])
    assert m.press(62, 0, 0.3, 1.5)["note"] == 0  # 200 ms late for note 0, near note 1
    assert m.press(62, 0, 0.52, 1.5)["note"] == 1


def test_windows_grades_and_nearest_note():
    m = PlayMatcher.for_song(SONG, ["R"])
    rate = 1.0  # 60 bpm: 1 beat = 1 s
    assert m.press(60, 0, 0.04, rate)["grade"] == "perfect"
    assert m.press(62, 0, 1.10, rate)["grade"] == "good"
    assert m.press(64, 0, 1.80, rate)["grade"] == "early"  # -200 ms
    assert m.press(65, 0, 3.24, rate)["grade"] == "late"
    r = m.press(67, 0, 3.70, rate)  # -300 ms: outside the window, 2 keys from 65 (beat 3, done) ...
    assert r["result"] == "wrong"
    assert config.PLAY_PERFECT_S == 0.05 and config.PLAY_GOOD_S == 0.12 and config.PLAY_WINDOW_S == 0.25


def _repeat_song(pitch, n, step):
    return {**SONG, "notes": [{"id": i, "pitch": pitch, "start": i * step, "dur": step, "hand": "R", "finger": 1,
                                "vel": 80} for i in range(n)]}


def test_fast_repeated_keys_after_a_missed_note_take_the_nearest():
    """Review fix 5: 150 bpm eighths (200 ms apart), the first note missed: each on-time press
    takes its own note (nearest), not the earlier missed one (that gave 5 false 'late')."""
    m = PlayMatcher.for_song(_repeat_song(60, 6, 0.5), ["R"])
    rate = 2.5
    for i in range(1, 6):
        r = m.press(60, 0, i * 0.5 + 0.004, rate)
        assert r["note"] == i and r["grade"] == "perfect", (i, r)
    sc = m.finish(3.0)
    assert sc["missed"] == 1 and sc["late"] == 0 and sc["perfect"] == 5


def test_nearest_only_when_the_later_note_is_within_good():
    m = PlayMatcher.for_song(_repeat_song(60, 2, 0.5), ["R"])
    # 150 ms late for note 0 and 150 ms early for note 1 (rate 1.5): neither within good -> earliest.
    assert m.press(60, 0, 0.225, 1.5)["note"] == 0
    m = PlayMatcher.for_song(_repeat_song(60, 2, 0.5), ["R"])
    # 210 ms late for note 0, 120 ms early for note 1 (within good) -> nearest (note 1).
    r = m.press(60, 0, 0.32, 1.5)
    assert r["note"] == 1 and r["grade"] == "good"
    m = PlayMatcher.for_song(_repeat_song(60, 2, 0.5), ["R"])
    # 100 ms late for note 0 (within good): earliest even with note 1 near.
    assert m.press(60, 0, 0.15, 1.5)["note"] == 0


def test_a_missed_note_is_closed_after_a_speed_change():
    """Review fix 6: a faster speed makes the window wider in beats; a note that is already
    'miss' must not take a press."""
    m = PlayMatcher.for_song(SONG, ["R"])
    assert [n.index for n in m.advance(0.3, 1.0)] == [0]  # note 0 missed (window 0.25 s)
    r = m.press(60, 0, 0.3, 2.0)  # at 2 beats a second the window is 0.5 beat: note 0 inside
    assert r["result"] == "wrong"
    assert m.notes[0].grade == "miss"


def test_windows_are_real_time_at_the_current_speed():
    m = PlayMatcher.for_song(SONG, ["R"])
    # At 2 beats a second, 0.1 beat = 50 ms: perfect.
    assert m.press(60, 0, 0.1, 2.0)["grade"] == "perfect"
    assert m.press(62, 0, 1.3, 2.0)["grade"] == "late"  # 150 ms


def test_extra_note_and_slip_and_short():
    m = PlayMatcher.for_song(SONG, ["R"])
    r = m.press(61, 0, 0.0, 1.0, 70)  # next to 60 (finger 1): a likely slip
    assert r["result"] == "wrong" and r["slip"] and r["intended"] == 60 and r["finger"] == 1
    r = m.press(80, 0, 0.0, 1.0)  # far: a plain extra note
    assert r["result"] == "wrong" and not r["slip"]
    assert m.press(62, 0, 1.0, 1.0)["result"] == "hit"
    assert m.release(62, 0, 1.5)["short"]  # 0.5 of 1 beat < 60%
    assert m.press(64, 0, 2.0, 1.0)["result"] == "hit"
    assert not m.release(64, 0, 2.7)["short"]
    m.advance(10, 1.0)
    sc = m.finish(8.0)
    assert sc["slips"] == 1 and sc["extra"] == 1 and sc["missed"] == 6 and sc["short"] == 1


def test_exact_run_scores_100_and_three_stars():
    m = PlayMatcher.for_song(SONG, ["R"])
    for n in NOTES:
        m.press(n["pitch"], 0, n["start"], 1.0)
        m.release(n["pitch"], 0, n["start"] + 0.9)
    sc = m.finish(8.0)
    assert sc["total"] == 100 and sc["stars"] == 3 and sc["accuracy"] == 100 and sc["timing"] == 100
    assert sc["length"] == 100


def test_score_formula():
    notes = [{"grade": g, "dur": 1.0, "short": False, "err_ms": 0} for g in ["perfect"] * 8 + ["early", "miss"]]
    sc = score_of(notes, [{"slip_of": None}])
    # accuracy 9 / 11 = 81.8; timing 8/9 = 88.9; length 100 -> 81.8 * (0.6 + 0.222 + 0.15) = 79.5
    assert sc["accuracy"] == 81.8 and sc["timing"] == 88.9 and sc["total"] == 80 and sc["stars"] == 2


# ---------------------------------------------------------------------- acceptance 1 (fake clock)


@pytest.mark.parametrize("song_id", BUILTIN)
def test_exact_fake_player_scores_at_least_98_each_song(song_id):
    song = songs.get(song_id)
    for hands in ({"R"}, {"L"}, {"R", "L"}):
        if not hands <= {n["hand"] for n in song["notes"]}:
            continue
        p, events, _ = simulate(song, sorted(hands, key="RL".index))
        end = of(events, "practice_end")[0]
        assert end["mode"] == "play" and end["score"]["total"] >= 98, (song_id, hands, end["score"])
        assert end["score"]["missed"] == 0 and not of(events, "practice_wrong")


def test_slower_speed_still_exact():
    p, events, _ = simulate(songs.get("ode-to-joy"), ["R"], speed=0.6)
    assert of(events, "practice_end")[0]["score"]["total"] == 100


# ---------------------------------------------------------------------- live feedback (PLAN 7.1)


def test_live_events_and_tips_at_most_one_each_4_seconds():
    song = songs.get("ode-to-joy")
    p, events, plan = simulate(song, ["R"], {"shift_ms": -180, "slip_rate": 0.3, "seed": 3})
    hits = of(events, "practice_hit")
    assert hits and all(h["grade"] in ("early", "good", "perfect", "late") for h in hits)
    wrong = of(events, "practice_wrong")
    assert any(w["slip"] and w["finger"] for w in wrong)
    tips = of(events, "practice_tip")
    assert tips
    texts = {t["text"] for t in tips}
    assert texts <= {"Wait for the click.", "Keep the key down longer."} | {f"Use finger {f} here." for f in range(1, 6)}
    # Tip times: from the key events that made them (t of the hit/wrong just before).
    ts = []
    for e in events:
        if e["type"] in ("practice_hit", "practice_wrong"):
            last = e["t"]
        if e["type"] == "practice_tip":
            ts.append(last)
    assert all(b - a >= config.TIP_INTERVAL_S - 1e-6 for a, b in zip(ts, ts[1:])), ts


def test_tips_rules():
    tips = feedback.LiveTips()
    early = {"result": "hit", "grade": "early"}
    assert tips.on_press(early, 0) is None and tips.on_press(early, 0.5) is None
    assert tips.on_press(early, 1.0)["text"] == "Wait for [[beat|the beat|the click]]."
    assert feedback.render(feedback.TIPS["wait_click"], set()) == "Wait for the click."
    assert feedback.render(feedback.TIPS["wait_click"], {"beat"}) == "Wait for [[beat|the beat]]."
    assert tips.on_press({"result": "wrong", "slip": True, "finger": 3}, 2.0) is None  # < 4 s
    assert tips.on_press({"result": "wrong", "slip": True, "finger": 3}, 5.0)["text"] == "Use finger 3 here."
    short = {"short": True, "checked": True}
    assert tips.on_release(short, 10) is None
    assert tips.on_release(short, 10.5)["text"] == "Keep the key down longer."


def test_stop_pauses_and_continue_from_here():
    song = songs.get("ode-to-joy")
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    st = p.start(song, mode="play", hands=["R"], count_in=False, accompany=False)
    rate = st["rate"]
    notes = sorted((n for n in song["notes"] if n["hand"] == "R"), key=lambda n: n["start"])
    for n in notes[:4]:  # play 4 notes, then stop
        clk.t = st["anchor_t"] + n["start"] / rate
        p.on_midi({"type": "note_on", "pitch": n["pitch"], "t": clk.t})
        p.on_midi({"type": "note_off", "pitch": n["pitch"], "t": clk.t + n["dur"] / rate * 0.9})
        p.tick(clk.t)
    last = clk.t
    while clk.t < last + 4 and not p.state()["paused"]:
        clk.t += 0.01
        p.tick(clk.t)
    s = p.state()
    assert s["paused"] and s["pause_reason"] == "stopped" and s["stop_beat"] == notes[4]["start"]
    assert clk.t - last > config.PLAY_STOP_GAP_S
    assert s["beat"] == notes[4]["start"]  # the view shows the stop point at the line
    # "Continue from here": the notes from there get a new chance; one group of clicks first.
    s = p.seek(s["stop_beat"], run=s["run"])
    assert s["running"] and s["lead_to"] == notes[4]["start"] and s["anchor_beat"] == notes[4]["start"] - 4
    at, ab = s["anchor_t"], s["anchor_beat"]
    for n in notes[4:]:
        clk.t = at + (n["start"] - ab) / rate
        p.tick(clk.t)
        p.on_midi({"type": "note_on", "pitch": n["pitch"], "t": clk.t})
        clk.t += n["dur"] / rate * 0.9
        p.on_midi({"type": "note_off", "pitch": n["pitch"], "t": clk.t})
    clk.t = at + (song["end"] - ab) / rate + 0.5
    p.tick(clk.t)
    end = of(events, "practice_end")[0]
    assert end["score"]["missed"] == 0 and end["score"]["total"] == 100


def drive_loop(p, clk, notes, passes, offset_s=None, step=0.002):
    """Play `passes` passes of a repeated part. Each note is pressed at its time + offset_s(pass, note)
    seconds (song clock, any speed changes included). Returns when the last pass is scored."""
    st = p.state()
    start, end = st["range"]
    length = end - start
    todo = [(j, k, n) for j in range(passes) for k, n in enumerate(notes)]
    offs = {(j, k): (offset_s(j, k) if offset_s else 0.0) for j, k, _ in todo}
    ups = []
    i = 0
    stop_t = clk.t + 600
    while clk.t < stop_t:
        st = p.state()
        v = p.passes * length + (st["beat"] - start)  # virtual beat over all passes
        while i < len(todo):
            j, k, n = todo[i]
            if v + 1e-9 < j * length + (n["start"] - start) + offs[(j, k)] * st["rate"]:
                break
            p.on_midi({"type": "note_on", "pitch": n["pitch"], "t": clk.t})
            ups.append((clk.t + n["dur"] / st["rate"] * 0.9, n["pitch"]))
            i += 1
        for u in [u for u in ups if u[0] <= clk.t]:
            p.on_midi({"type": "note_off", "pitch": u[1], "t": u[0]})
            ups.remove(u)
        p.tick(clk.t)
        if len([e for e in p._events if e["type"] == "practice_pass"]) >= passes:
            return
        clk.t += step
    raise AssertionError("the passes did not end")


def loop_practice(song, speed, section=0, hands=("R",)):
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    p._events = events
    p.start(song, mode="play", hands=list(hands), speed=speed, section=section, count_in=False, accompany=False)
    return p, clk, events


def test_loop_auto_step_after_3_clean_passes():
    """PLAN 6.3 Loop: +5% after 3 clean runs (passes of the repeated part)."""
    song = songs.get("ode-to-joy")
    p, clk, events = loop_practice(song, 0.7)
    notes = sorted((n for n in song["notes"] if n["hand"] == "R" and n["start"] < 16), key=lambda n: n["start"])
    drive_loop(p, clk, notes, 4)
    passes = of(events, "practice_pass")
    assert [x["score"]["total"] for x in passes] == [100] * 4
    assert passes[2]["adapt"]["action"] == "faster" and passes[2]["adapt"]["speed"] == 0.75
    assert passes[3]["speed"] == 0.75 and passes[3]["adapt"] is None  # the count starts again
    assert passes[2]["adapt"]["text"] == "3 good runs in a row. The app made the speed faster: 75%."


def test_loop_early_press_at_the_wrap_and_late_press_after_it():
    """Review fix 1: a loop has no lead-in. The first note pressed 100 ms early (before the wrap)
    counts for the next pass; the last note pressed 100 ms late (after the wrap) counts for the
    pass before. No extra notes, no missed notes."""
    song = songs.get("ode-to-joy")
    p, clk, events = loop_practice(song, 1.0)
    notes = sorted((n for n in song["notes"] if n["hand"] == "R" and n["start"] < 16), key=lambda n: n["start"])
    last = len(notes) - 1

    def off(j, k):
        if k == 0 and j > 0:
            return -0.10
        if k == last:
            return 0.10
        return 0.0
    drive_loop(p, clk, notes, 3, off)
    passes = of(events, "practice_pass")
    for x in passes:
        sc = x["score"]
        assert sc["missed"] == 0 and sc["extra"] == 0 and sc["slips"] == 0, sc
        assert sc["total"] == 100, sc
    assert passes[1]["log"]["notes"][0]["err_ms"] == pytest.approx(-100, abs=3)
    assert passes[0]["log"]["notes"][last]["err_ms"] == pytest.approx(100, abs=3)
    # 200 ms early for the first note: still the next pass (early grade), not an extra note.
    p, clk, events = loop_practice(song, 1.0)
    drive_loop(p, clk, notes, 2, lambda j, k: -0.2 if (k == 0 and j > 0) else 0.0)
    sc = of(events, "practice_pass")[1]["score"]
    assert sc["missed"] == 0 and sc["extra"] == 0 and sc["early"] == 1


def test_pause_back_in_play_along_rewinds_the_notes():
    """Review fix 3: pause with at_beat (hidden window) moves the clock back; the notes from there
    get a new chance, so playing them again is not 'extra'."""
    song = songs.get("ode-to-joy")
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    st = p.start(song, mode="play", hands=["R"], count_in=False, accompany=False)
    rate = st["rate"]
    notes = sorted((n for n in song["notes"] if n["hand"] == "R"), key=lambda n: n["start"])

    def play(ns, at, ab):
        for n in ns:
            clk.t = at + (n["start"] - ab) / rate
            p.tick(clk.t)
            p.on_midi({"type": "note_on", "pitch": n["pitch"], "t": clk.t})
            p.on_midi({"type": "note_off", "pitch": n["pitch"], "t": clk.t + n["dur"] / rate * 0.9})
    play(notes[:8], st["anchor_t"], st["anchor_beat"])
    clk.t += 0.05
    back = notes[5]["start"]
    s = p.pause(at_beat=back, run=st["run"])
    assert s["beat"] == back
    clk.t += 1.0
    s = p.resume()
    play(notes[5:], s["anchor_t"], s["anchor_beat"])
    clk.t = s["anchor_t"] + (song["end"] - s["anchor_beat"]) / rate + 0.5
    p.tick(clk.t)
    sc = of(events, "practice_end")[0]["score"]
    assert sc["extra"] == 0 and sc["missed"] == 0 and sc["total"] == 100, sc


def test_latency_calibration_takes_the_offset_away():
    """Review fix 4: with a constant +80 ms user delay, the calibrated offset gives no dragging."""
    song = songs.get("ode-to-joy")
    for cal, want_drag in ((0.0, True), (0.08, False)):
        hist, res = [], None
        for k in range(3):
            clk = Clock()
            events = []
            p = Practice(events.append, now=clk, threaded=False)
            p.input_offset_s = cal
            st = p.start(song, mode="play", hands=["R"], count_in=True, accompany=False)
            plan = play_plan(song, ["R"], start=st["range"][0], end=st["range"][1], jitter_ms=30, shift_ms=80,
                             seed=10 + k)
            at, ab, rate = st["anchor_t"], st["anchor_beat"], st["rate"]
            keys = timed_events(plan, lambda b: at + (b - ab) / rate)
            end_t = at + (st["range"][1] - ab) / rate + 1.0
            i = 0
            while clk.t < end_t and not p.state()["done"]:
                while i < len(keys) and keys[i][0] <= clk.t:
                    t, on, pitch, vel = keys[i]
                    p.on_midi({"type": "note_on" if on else "note_off", "pitch": pitch, "velocity": vel, "t": t})
                    i += 1
                p.tick(clk.t)
                clk.t += 0.005
            end = of(events, "practice_end")[0]
            res = feedback.analyze(song, end, hist)
            hist.insert(0, {"range": end["range"], "bar_errors": feedback.bar_errors(song, end["log"])})
        ids = {f["id"] for f in res["all"]}
        assert ("dragging" in ids) == want_drag, (cal, ids, end["score"]["mean_err_ms"])
        if cal:
            assert abs(end["score"]["mean_err_ms"]) < 20


# ---------------------------------------------------------------------- findings (PLAN 7.2, acceptance 2)


def run_findings(song, hands, kw, runs=3, unlocked=()):
    """`runs` runs with the same errors (other seeds); returns the analysis of the last run."""
    hist = []
    out = None
    for k in range(runs):
        kw2 = {**kw, "seed": kw.get("seed", 0) * 100 + k}
        _, events, plan = simulate(song, hands, kw2)
        end = of(events, "practice_end")[0]
        out = feedback.analyze(song, end, hist, unlocked)
        hist.insert(0, {"range": end["range"], "bar_errors": feedback.bar_errors(song, end["log"])})
    return out, end, plan


def test_findings_hard_bar_slips_rushing():
    song = songs.get("twinkle-twinkle")
    res, end, plan = run_findings(song, ["R"], {"jitter_ms": 150, "shift_ms": -80, "slip_rate": 0.1, "hard_bar": 3,
                                                 "seed": 1})
    ids = [f["id"] for f in res["all"]]
    assert "hard_spot" in ids and "rushing" in ids and "dragging" not in ids, ids
    hard = next(f for f in res["all"] if f["id"] == "hard_spot")
    assert hard["data"]["bar"] == 3 and hard["place"]["start"] == 8.0 and hard["place"]["end"] == 12.0
    assert hard["text"] == "This part is hard for you. It is in Part 1."
    assert hard["action"]["id"] == "loop_slow" and hard["action"]["speed"] == 0.6
    assert end["score"]["slips"] == len(plan["slips"])
    assert len(plan["slips"]) >= 3 and "slips" in ids  # seed 1: 4 slips in the last run
    assert len(res["findings"]) <= 3 and res["findings"][0]["id"] == "hard_spot"


def test_findings_dragging_and_none_without_shift():
    song = songs.get("ode-to-joy")
    res, _, _ = run_findings(song, ["R"], {"jitter_ms": 150, "shift_ms": 90, "seed": 2})
    ids = [f["id"] for f in res["all"]]
    assert "dragging" in ids and "rushing" not in ids and "hard_spot" not in ids
    res, _, _ = run_findings(song, ["R"], {"jitter_ms": 150, "seed": 2})
    assert not {"rushing", "dragging", "hard_spot"} & {f["id"] for f in res["all"]}


def test_hard_spot_needs_2_of_the_last_3_runs():
    song = songs.get("twinkle-twinkle")
    res, _, _ = run_findings(song, ["R"], {"hard_bar": 2}, runs=1)
    assert "hard_spot" not in [f["id"] for f in res["all"]]
    res, _, _ = run_findings(song, ["R"], {"hard_bar": 2}, runs=2)
    assert "hard_spot" in [f["id"] for f in res["all"]]


def test_hard_spot_words_after_bar_unlock():
    song = songs.get("twinkle-twinkle")
    res, _, _ = run_findings(song, ["R"], {"hard_bar": 3}, runs=2, unlocked={"bar"})
    hard = next(f for f in res["all"] if f["id"] == "hard_spot")
    assert hard["text"] == "This part ([[bar|bar 3]]) is hard for you. It is in Part 1."
    locked = feedback.render(feedback.MESSAGES["hard_spot_bar"].format(bar=3), set())
    assert locked == "This part (group of clicks 3) is hard for you."


def _log(notes, extras=()):
    return {"notes": notes, "extras": list(extras)}


def _n(i, start, pitch, hand="R", grade="perfect", err=0.0, dur=1.0, vel=80, short=False, slip=None):
    return {"i": i, "start": start, "dur": dur, "pitch": pitch, "hand": hand, "finger": 1, "grade": grade,
            "err_ms": None if grade == "miss" else err, "short": short, "vel": None if grade == "miss" else vel,
            "want_vel": 80, "slip": slip}


SONG2 = {"id": "s2", "title": "S2", "bpm": 60, "time_signature": [4, 4], "end": 16.0, "notes": [],
         "sections": [{"name": "Part 1", "start": 0, "end": 16}],
         "hand_positions": [{"hand": "R", "start": 0, "thumb_pitch": 60}, {"hand": "R", "start": 8, "thumb_pitch": 67}]}


def _run(notes, hands=("R",), extras=(), total=80, length=100):
    return {"log": _log(notes, extras), "hands": list(hands), "range": [0, 16], "speed": 1.0,
            "score": {"total": total, "length": length}}


def test_hand_problem_and_coordination():
    notes = [_n(i, i, 60) for i in range(10)] + [_n(10 + i, i, 48, "L", "miss" if i < 4 else "perfect") for i in range(10)]
    res = feedback.analyze(SONG2, _run(notes, ("R", "L"), total=65), [], (), None, {"R": 90, "L": 88})
    ids = [f["id"] for f in res["all"]]
    assert "hand_problem" in ids and "coordination" in ids
    hp = next(f for f in res["all"] if f["id"] == "hand_problem")
    assert hp["text"] == "Your left hand needs more practice." and hp["action"]["hands"] == ["L"]
    co = next(f for f in res["all"] if f["id"] == "coordination")
    assert co["action"] == {"id": "both_half", "label": "Both hands, half speed", "hands": ["R", "L"], "speed": 0.5}
    res = feedback.analyze(SONG2, _run(notes, ("R", "L"), total=65), [], (), None, {"R": 90, "L": 70})
    assert "coordination" not in [f["id"] for f in res["all"]]


def test_hand_move_finding():
    notes = [_n(i, i, 60 + i % 5) for i in range(16)]
    notes[8]["grade"] = "miss"
    notes[9]["grade"] = "late"
    notes[9]["err_ms"] = 200
    res = feedback.analyze(SONG2, _run(notes), [])
    f = next(f for f in res["all"] if f["id"] == "hand_move")
    assert f["place"]["start"] == 6 and f["place"]["end"] == 10 and f["action"]["id"] == "move_loop"


def test_chord_missing_key_finding():
    notes = []
    for k in range(4):
        b = 4.0 * k
        notes += [_n(3 * k, b, 60), _n(3 * k + 1, b, 64, grade="miss" if k < 2 else "perfect"), _n(3 * k + 2, b, 67)]
    res = feedback.analyze(SONG2, _run(notes), [])
    f = next(f for f in res["all"] if f["id"] == "chord")
    assert f["text"] == "Press all 3 keys together." and f["keys"] == [60, 64, 67]
    assert f["action"]["label"] == "Practice these 3 keys" and f["action"]["mode"] == "wait"


def test_uneven_touch_and_short_notes():
    notes = [_n(i, i, 60, vel=40 if i % 2 else 110) for i in range(10)]
    res = feedback.analyze(SONG2, _run(notes, length=40), [])
    ids = [f["id"] for f in res["all"]]
    assert "uneven" in ids and "short_notes" in ids
    assert next(f for f in res["all"] if f["id"] == "short_notes")["text"] == "Hold the key down until the falling note ends."
    even = [_n(i, i, 60, vel=80 + (i % 3)) for i in range(10)]
    assert "uneven" not in [f["id"] for f in feedback.analyze(SONG2, _run(even), [])["all"]]
    # with the setup touch range, the limit is a share of the range
    narrow = [_n(i, i, 60, vel=65 if i % 2 else 95) for i in range(10)]  # SD 15 > 25% of 40
    assert "uneven" in [f["id"] for f in feedback.analyze(SONG2, _run(narrow), [], (), [60, 100])["all"]]


def test_at_most_3_findings_most_important_first():
    notes = [_n(i, i, 60 + i % 3, vel=40 if i % 2 else 110, err=-90) for i in range(16)]
    for i in (1, 5, 9):
        notes[i].update(grade="miss", slip=61, err_ms=None, vel=None)
    res = feedback.analyze(SONG2, _run(notes, length=40, extras=[{"beat": 1, "pitch": 61, "slip_of": 1}]), [])
    ids = [f["id"] for f in res["all"]]
    assert ids == [k for k in feedback.PRIORITY if k in ids]
    assert len(res["findings"]) == 3 and [f["id"] for f in res["findings"]] == ids[:3]


# ---------------------------------------------------------------------- automatic adapt (PLAN 7.3, acceptance 3)


def runs_of(scores, speed):
    return [{"score": s, "speed": speed} for s in scores]  # newest first


def test_adapt_3_failed_runs_slower_min_40():
    assert feedback.adapt(runs_of([50, 40, 59], 1.0), 1.0) == {"action": "slower", "speed": 0.85}
    assert feedback.adapt(runs_of([50, 40], 1.0), 1.0) is None  # only 2 runs
    assert feedback.adapt(runs_of([50, 70, 40], 1.0), 1.0) is None  # not 3 in a row
    assert feedback.adapt(runs_of([10, 10, 10], 0.5), 0.5) == {"action": "slower", "speed": 0.4}
    assert feedback.adapt(runs_of([10, 10, 10], 0.4), 0.4) is None  # minimum 40%


def test_adapt_counts_only_runs_at_the_current_speed():
    runs = runs_of([50, 50], 0.85) + runs_of([50], 1.0)
    assert feedback.adapt(runs, 0.85) is None


def test_adapt_3_clean_runs_faster_up_to_100_then_next_step():
    assert feedback.adapt(runs_of([90, 92, 94], 0.6), 0.6) == {"action": "faster", "speed": 0.65}
    assert feedback.adapt(runs_of([95, 99, 100], 0.6), 0.6) == {"action": "faster", "speed": 0.7}
    assert feedback.adapt(runs_of([100, 100, 100], 0.95), 0.95) == {"action": "faster", "speed": 1.0}
    assert feedback.adapt(runs_of([100, 100, 100], 1.0), 1.0) == {"action": "top", "speed": 1.0}
    song = songs.get("frere-jacques-both-hands")
    assert feedback.next_step(song, ["R"], None, None)["id"] == "both"
    assert feedback.next_step(song, ["R", "L"], 0, None) == {"id": "part", "section": 1,
                                                            "text": "3 good runs in a row at full speed. Next step: play Part 2."}
    assert feedback.next_step(song, ["R", "L"], None, [0, 4])["id"] == "whole"
    assert feedback.next_step(songs.get("mary-had-a-little-lamb"), ["R"], None, None)["id"] == "song"


def _play_end(song_id, hands, total, speed=1.0, section=None, song=None):
    song = song or songs.get(song_id)
    notes = [_n(i, n["start"], n["pitch"], n["hand"]) for i, n in enumerate(song["notes"]) if n["hand"] in hands]
    return {"type": "practice_end", "song_id": song_id, "mode": "play", "completed": True, "hands": list(hands),
            "wrong": 0, "stops": len(notes), "accuracy": float(total), "speed": speed, "section": section, "span": None,
            "range": [0, song["end"]], "seconds": 20.0, "errors": [],
            "score": {"total": total, "accuracy": float(total), "timing": 100.0, "length": 100.0, "stars": 3, "hit": len(notes)},
            "log": {"notes": notes, "extras": []}}


def test_adapt_end_to_end_through_the_server(client):
    """3 failed runs -> slower (course event), 3 clean runs at 85% -> faster, ... at 100% -> next step."""
    c = client
    hub = c.app_ref.state.hub
    published = []
    orig = hub.publish
    hub.publish = lambda e: (published.append(e), orig(e))

    def run(total, speed):
        c.riyaz["practice"].sink(_play_end("ode-to-joy", ["R"], total, speed))
        c.riyaz["flush_results"]()
        return [e for e in published if e.get("type") == "course"][-1]

    assert run(40, 1.0)["adapt"] is None
    assert run(50, 1.0)["adapt"] is None
    r = run(55, 1.0)
    assert r["adapt"]["action"] == "slower" and r["adapt"]["speed"] == 0.85
    assert r["adapt"]["text"] == "The last 3 runs were hard. The app made the speed slower: 85%."
    for total in (90, 91):
        assert run(total, 0.85)["adapt"] is None
    r = run(92, 0.85)
    assert r["adapt"] == {"action": "faster", "speed": 0.9,
                          "text": "3 good runs in a row. The app made the speed faster: 90%."}
    for _ in range(2):
        run(96, 1.0)
    r = run(97, 1.0)
    assert r["adapt"]["action"] == "next" and r["adapt"]["next"]["id"] == "song"
    assert r["done"] and r["learned"] is False  # learned on the first run >= 85 at 100%
    # The setting turns it off.
    c.post("/api/settings/practice", json={"adapt": False})
    for _ in range(3):
        r = run(10, 1.0)
    assert r["adapt"] is None


def test_learned_song_schedules_reviews(client):
    c = client
    hub = c.app_ref.state.hub
    published = []
    orig = hub.publish
    hub.publish = lambda e: (published.append(e), orig(e))
    c.riyaz["practice"].sink(_play_end("ode-to-joy", ["R"], 84))
    c.riyaz["flush_results"]()
    r = [e for e in published if e.get("type") == "course"][-1]
    assert r["done"] and not r["learned"]  # done at 80, learned at 85
    c.riyaz["practice"].sink(_play_end("ode-to-joy", ["R"], 88))
    c.riyaz["flush_results"]()
    r = [e for e in published if e.get("type") == "course"][-1]
    assert r["learned"] and r["adapt"]["learned_text"].startswith("You learned this song.")
    items = c.riyaz["store"].reviews()
    assert [i["item"] for i in items] == ["section:ode-to-joy:0", "section:ode-to-joy:1"]
    assert all(i["interval_days"] == 1 for i in items)
    prog = c.get("/api/progress").json()
    assert {s["id"] for s in prog["skills"]} == {"keys", "rhythm", "right", "left", "coordination", "chords", "scales", "ear"}
    assert prog["songs"][0]["song_id"] == "ode-to-joy" and [p["value"] for p in prog["songs"][0]["points"]] == [84, 88]
    assert len(prog["reviews"]) == 2 and prog["reviews"][0]["part"] == "Part 1"


def test_loop_passes_stay_out_of_history_and_progress(client):
    """Review fix 2: loop passes are saved (skill model) but not in the run history (findings,
    adapt, coordination) or the Progress chart. The Loop +5% step is in practice.py (own count)."""
    c = client
    for total in (30, 30, 30):
        ev = {**_play_end("ode-to-joy", ["R"], total, section=0), "type": "practice_pass", "pass": 1, "adapt": None}
        c.riyaz["practice"].sink(ev)
    c.riyaz["flush_results"]()
    atts = c.riyaz["store"].attempts(kind="song", item="ode-to-joy", limit=10)
    assert len(atts) == 3 and all(a["data"].get("loop_pass") for a in atts)
    prog = c.get("/api/progress").json()
    assert not [s for s in prog["songs"] if s["song_id"] == "ode-to-joy"]
    published = []
    hub = c.app_ref.state.hub
    orig = hub.publish
    hub.publish = lambda e: (published.append(e), orig(e))
    c.riyaz["practice"].sink(_play_end("ode-to-joy", ["R"], 40, section=0))
    c.riyaz["flush_results"]()
    r = [e for e in published if e.get("type") == "course"][-1]
    assert r["adapt"] is None  # one real run below 60 (the 3 passes do not count): no "slower"
    prog = c.get("/api/progress").json()
    assert [p["value"] for p in prog["songs"][0]["points"]] == [40]


def test_review_counts_only_at_full_speed_with_the_ladder_hands(client):
    """Review fix 7: a slow or one-hand run of a learned song does not change its review."""
    c = client
    st = c.riyaz["store"]
    c.riyaz["practice"].sink(_play_end("frere-jacques-both-hands", ["R", "L"], 95))
    c.riyaz["flush_results"]()
    items = st.reviews()
    assert items, "the song is learned"
    for r in items:
        st.save_review({**r, "due": "2000-01-01"})
    c.riyaz["practice"].sink(_play_end("frere-jacques-both-hands", ["R", "L"], 95, speed=0.8))
    c.riyaz["practice"].sink(_play_end("frere-jacques-both-hands", ["R"], 95))
    c.riyaz["flush_results"]()
    assert all((r["reps"] or 0) == 0 for r in st.reviews())
    c.riyaz["practice"].sink(_play_end("frere-jacques-both-hands", ["R", "L"], 95))
    c.riyaz["flush_results"]()
    assert all(r["reps"] == 1 and r["interval_days"] == 2 for r in st.reviews())


def test_findings_in_the_course_event(client):
    c = client
    hub = c.app_ref.state.hub
    published = []
    orig = hub.publish
    hub.publish = lambda e: (published.append(e), orig(e))
    song = songs.get("twinkle-twinkle")
    for k in range(2):
        _, events, _ = simulate(song, ["R"], {"jitter_ms": 150, "shift_ms": -80, "hard_bar": 3, "seed": k})
        c.riyaz["practice"].sink(of(events, "practice_end")[0])
        c.riyaz["flush_results"]()
    r = [e for e in published if e.get("type") == "course"][-1]
    ids = [f["id"] for f in r["findings"]]
    assert ids[0] == "hard_spot" and "rushing" in ids and r["all_findings"][:len(ids)] == ids


# ---------------------------------------------------------------------- spaced repetition (PLAN 9.3)


def test_spaced_repetition_schedule(store):
    song = songs.get("ode-to-joy")
    assert review.add_song(store, song, "2026-11-10") == ["section:ode-to-joy:0", "section:ode-to-joy:1"]
    item = "section:ode-to-joy:0"
    assert store.review(item)["due"] == "2026-11-11"
    review.record(store, item, 95, "2026-11-10")  # not due yet: no change
    assert store.review(item)["interval_days"] == 1 and store.review(item)["reps"] == 0
    r = review.record(store, item, 90, "2026-11-11")  # >= 85: x 2
    assert r["interval_days"] == 2 and r["due"] == "2026-11-13"
    r = review.record(store, item, 70, "2026-11-13")  # 60-84: same
    assert r["interval_days"] == 2 and r["due"] == "2026-11-15"
    r = review.record(store, item, 95, "2026-11-15")
    assert r["interval_days"] == 4 and r["due"] == "2026-11-19"
    assert review.record(store, item, 30, "2026-11-15")["interval_days"] == 4  # one review a day
    r = review.record(store, item, 30, "2026-11-20")  # < 60: 1 day
    assert r["interval_days"] == 1 and r["due"] == "2026-11-21"
    assert [d["item"] for d in review.due(store, "2026-11-21")] == ["section:ode-to-joy:1", item]
    assert review.find_key_score([1.5, 2.0], 0) == 100 and review.find_key_score([4.0], 1) == 65


def test_session_review_block_uses_the_due_item(client):
    st = c_store = client.riyaz["store"]
    review.add_song(st, songs.get("london-bridge"), "2000-01-01")
    plan = client.get("/api/today").json()["plan"]
    rb = next(b for b in plan["blocks"] if b["kind"] == "review")
    assert rb["why"] == "due" and rb["song_id"] == "london-bridge" and rb["mode"] == "play"
    assert rb["section"] == 0 and c_store is st


def test_find_key_drill_is_a_review_item(client):
    c = client
    drill = c.riyaz["drill"]
    st = c.post("/api/drill/start", json={"source": "find_key", "seed": 1}).json()
    assert st["kind"] == "find_key"
    for _ in range(config.FIND_KEY_ROUNDS):
        d = drill.state()
        p = d["expect"]["any"][0]
        c.riyaz["practice"].on_midi  # noqa: B018
        drill.on_midi({"type": "note_on", "pitch": p, "t": None})
        drill.on_midi({"type": "note_off", "pitch": p, "t": None})
    assert drill.state()["status"] == "passed"
    r = c.riyaz["store"].review(review.FIND_KEY)
    assert r is not None and r["kind"] == "drill" and r["reps"] == 1


# ---------------------------------------------------------------------- skill model (PLAN 9.4)


def test_skill_model_from_results(store):
    for total, hands, acc in ((60, "R", {"R": 70.0}), (90, "RL", {"R": 95.0, "L": 60.0})):
        store.add_attempt(kind="song", item="frere-jacques-both-hands", day="2026-11-10", hands=list(hands),
                          completed=True, accuracy=float(total), speed=1.0,
                          data={"mode": "play", "score": {"total": total, "accuracy": float(total), "timing": 80.0, "hit": 10},
                                "hand_acc": acc, "groups_pct": None})
    store.add_attempt(kind="song", item="mary-had-a-little-lamb", day="2026-11-10", hands=["R"], completed=True,
                      accuracy=100.0, speed=1.0, data={"mode": "wait"})
    m = {s["id"]: s for s in skills.model(store)}
    assert m["left"]["value"] == 60.0 and m["left"]["n"] == 1
    assert m["right"]["n"] == 3 and m["coordination"]["value"] == 90.0 and m["rhythm"]["value"] == 80.0
    assert m["scales"]["value"] is None and m["ear"]["value"] is None
    assert m["chords"]["name"] == "Keys together" and m["scales"]["name"] == "8-key walks"
    assert skills.weakest(store, ["right", "left", "rhythm"]) == "left"
    assert skills.weakest(store, ["ear"]) is None


def test_weakest_skill_picks_the_warmup_hand(client):
    st = client.riyaz["store"]
    client.post("/api/course/skip", json={"level": 3})
    st.add_attempt(kind="song", item="frere-jacques-both-hands", day="2026-11-10", hands=["R", "L"], completed=True,
                   accuracy=70.0, speed=1.0, data={"mode": "play", "score": {"total": 70, "accuracy": 90.0, "timing": 95.0,
                                                                              "hit": 10}, "hand_acc": {"R": 98.0, "L": 40.0}})
    client.post("/api/settings/habit", json={"song_id": "frere-jacques-both-hands"})
    plan = client.get("/api/today").json()["plan"]
    warm = plan["blocks"][0]
    assert warm["focus"] == "left" and warm["hands"] == ["L"]
    assert all(s.get("hand", "L") == "L" for s in warm["drill"]["steps"])
    # Phase 5b: at Level 3 the ear games are open; "ear" has no results yet, so it is the weakest.
    assert plan["blocks"][3]["focus"] == "ear" and plan["blocks"][3]["exercise"] in ("echo", "interval")


# ---------------------------------------------------------------------- database and words


def test_database_v2_upgrades_to_v3(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    from riyaz import db as dbmod

    conn.executescript(dbmod._SCHEMA + "PRAGMA user_version = 2;")
    conn.execute("INSERT INTO song_progress(song_id, runs, done) VALUES('ode-to-joy', 3, 1)")
    conn.commit()
    conn.close()
    s = Store(path)
    assert s.schema_version() == 3
    row = s.song_progress("ode-to-joy")["ode-to-joy"]
    assert row["runs"] == 3 and row["done"] and not row["learned"] and row["best_score"] is None
    assert s.reviews() == []
    s.close()
    assert Store(path).schema_version() == 3  # again: no error


TERM_RE = {t["id"]: re.compile(rf"\b(?:{t['pattern']})\b", re.I) for t in course.content()["terms"]}


def test_rule_6_feedback_texts():
    """PLAN 7.4 Rule 6 for the Phase 4 texts (tips, findings, buttons, speed messages, skill names):
    rendered with no term unlocked (and with each single term), no locked term reaches the page."""
    texts = feedback.all_texts() + [(1, f"skill {k}", n) for k, n in skills.SKILLS]
    assert len(texts) > 30
    ids = [t["id"] for t in course.content()["terms"]]
    bad = []
    for _lvl, where, text in texts:
        for unlocked in [set()] + [{x} for x in ids]:
            out = course.TERM_MARK.sub("", course.render_text(text, unlocked))
            for tid, rx in TERM_RE.items():
                if tid not in unlocked and tid not in ("finger_number",) and rx.search(out):
                    bad.append((where, tid, out))
        shown = course.shown_text(text)
        assert (shown[0].isupper() or shown[0].isdigit()) and len(shown.split()) <= 25, (where, shown)
    assert not bad, bad[:5]


# ---------------------------------------------------------------------- latency calibration (review fix 4)


def test_tap_check_offset_math():
    from riyaz import tapcheck
    clicks = [10 + 0.75 * i for i in range(8)]
    r = tapcheck.compute(clicks, [c + 0.08 + d for c, d in zip(clicks, [0.01, -0.01, 0.0, 0.02, -0.02, 0.0, 0.005, 0.25])])
    assert r["ok"] and r["offset_ms"] == pytest.approx(80, abs=3) and r["taps"] == 8  # median: one bad tap does not count
    assert tapcheck.compute(clicks, [c + 0.08 for c in clicks[:4]])["reason"] == "few_taps"
    assert tapcheck.compute(clicks, [c + d for c, d in zip(clicks, [0, 0.3, -0.3, 0.2, -0.2, 0.25, -0.1, 0.1])])["reason"] == "uneven"
    assert tapcheck.compute(clicks, [c + 0.33 for c in clicks])["reason"] == "too_late"
    r = tapcheck.compute(clicks, [c - 0.03 for c in clicks])
    assert r["ok"] and r["offset_ms"] == 0  # before the click: no correction (0-300 ms)
    two = tapcheck.compute(clicks, [clicks[0] + 0.05, clicks[0] + 0.06] + [c + 0.05 for c in clicks[1:]])
    assert two["taps"] == 8  # the first press for each click
    assert "80 ms" in tapcheck.text_of({"ok": True, "offset_ms": 80.0})


def test_tap_check_through_the_server(client):
    c = client
    assert c.get("/api/settings/latency").json() == {"offset_ms": 0.0, "done": False, "max_ms": 300.0}
    plan = c.post("/api/settings/latency/start", json={}).json()
    assert len(plan["clicks"]) == config.TAP_CLICKS and plan["interval"] == config.TAP_INTERVAL_S
    tc = c.riyaz["tapcheck"]
    for k in plan["clicks"]:
        tc.on_midi({"type": "note_on", "pitch": 60, "velocity": 80, "t": k + 0.08})
    tc.on_midi({"type": "note_on", "pitch": 60, "velocity": 80, "t": plan["clicks"][0] - 10})  # long before: ignored
    r = c.post("/api/settings/latency/finish", json={}).json()
    assert r["ok"] and r["offset_ms"] == 80.0 and r["done"] and r["taps"] == 8
    assert r["text"] == ("Your key presses come 80 ms (0.08 seconds) after the click. "
                         "In Play along, the app now counts each key press this much earlier.")
    assert c.riyaz["practice"].input_offset_s == pytest.approx(0.08)
    assert c.get("/api/settings/latency").json()["offset_ms"] == 80.0
    # A failed check does not change the stored value.
    c.post("/api/settings/latency/start", json={})
    r = c.post("/api/settings/latency/finish", json={}).json()
    assert not r["ok"] and r["reason"] == "few_taps" and r["offset_ms"] == 80.0
    assert r["text"].startswith("The app got less than 5 key presses")
    assert c.post("/api/settings/latency/finish", json={}).json()["reason"] == "not_started"
    r = c.post("/api/settings/latency/reset", json={}).json()
    assert r == {"offset_ms": 0.0, "done": False, "max_ms": 300.0} and c.riyaz["practice"].input_offset_s == 0.0
    bad = c.post("/api/settings/latency/start", json={}, headers={"Origin": "http://evil.example"})
    assert bad.status_code == 403
