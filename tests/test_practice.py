"""Song clock, watch and wait mode, loop, speed, pause (PLAN 4 Timing, 6.3, 6.4). Fake clock, no MIDI."""

import mido
import pytest

from riyaz import songs
from riyaz.practice import Practice, PracticeError

SONG = {
    "id": "t", "title": "T", "bpm": 60, "time_signature": [4, 4], "end": 8.0,
    "notes": [
        {"id": 0, "pitch": 60, "start": 0.0, "dur": 1, "hand": "R", "finger": 1, "vel": 80},
        {"id": 1, "pitch": 48, "start": 0.0, "dur": 4, "hand": "L", "finger": 1, "vel": 60},
        {"id": 2, "pitch": 62, "start": 1.0, "dur": 1, "hand": "R", "finger": 2, "vel": 80},
        {"id": 3, "pitch": 64, "start": 4.0, "dur": 2, "hand": "R", "finger": 3, "vel": 80},
        {"id": 4, "pitch": 43, "start": 4.0, "dur": 4, "hand": "L", "finger": 4, "vel": 60},
        {"id": 5, "pitch": 65, "start": 6.0, "dur": 2, "hand": "R", "finger": 4, "vel": 80},
    ],
    "sections": [{"name": "Part 1", "start": 0.0, "end": 4.0}, {"name": "Part 2", "start": 4.0, "end": 8.0}],
}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeMidi:
    def __init__(self):
        self.sent = []

    def note_message(self, pitch, vel):
        return mido.Message("note_on", note=pitch, velocity=vel)

    def send(self, msg):
        self.sent.append((msg.note, msg.velocity))
        return True


@pytest.fixture
def env():
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    return p, clk, events


def of(events, kind):
    return [e for e in events if e["type"] == kind]


def key(p, clk, pitch, on=True):
    p.on_midi({"type": "note_on" if on else "note_off", "pitch": pitch, "t": clk.t})


def test_watch_mode_clock_count_in_and_end(env):
    p, clk, events = env
    s = p.start(SONG, mode="watch", hands=["R"], count_in=True)
    assert s["anchor_beat"] == -4.0 and s["rate"] == 1.0 and s["running"]
    clk.t += 4.0
    assert p.beat_now() == pytest.approx(0.0)
    clk.t += 3.0
    p.tick()
    assert p.beat_now() == pytest.approx(3.0)
    key(p, clk, 99)  # watch mode: keys are not checked
    assert not of(events, "practice_wrong")
    clk.t += 5.5
    p.tick()
    end = of(events, "practice_end")
    assert end and end[0]["completed"] and end[0]["mode"] == "watch"
    st = p.state()
    assert st["done"] and not st["running"] and st["beat"] == 8.0


def test_wait_mode_holds_until_correct_key(env):
    p, clk, events = env
    p.start(SONG, mode="wait", hands=["R"], count_in=False)
    clk.t += 0.5
    p.tick()
    assert p.state()["waiting"] and p.beat_now() == 0.0  # holds at the first note
    clk.t += 10
    assert p.beat_now() == 0.0
    key(p, clk, 61)  # wrong key
    w = of(events, "practice_wrong")
    assert w and w[0]["pitch"] == 61 and w[0]["expected"] == [60]
    assert p.beat_now() == 0.0 and p.state()["stop_index"] == 0 and p.state()["wrong"] == 1
    assert p.matcher.errors[0]["pitch"] == 61
    key(p, clk, 60)
    assert of(events, "practice_hit")[0]["pitch"] == 60
    st = p.state()
    assert st["stop_index"] == 1 and st["hold_beat"] == 1.0 and not st["waiting"]
    assert st["anchor_t"] == clk.t and st["anchor_beat"] == 0.0  # the clock goes on from now
    clk.t += 0.6
    assert p.beat_now() == pytest.approx(0.6)


def test_wait_mode_early_press_counts_inside_window(env):
    p, clk, events = env
    p.start(SONG, mode="wait", hands=["R"], count_in=False)
    key(p, clk, 60)  # beat 0: on time
    clk.t += 0.6  # beat 0.6: 0.4 before the next note (inside 0.5)
    key(p, clk, 62)
    assert p.state()["stop_index"] == 2 and p.state()["hold_beat"] == 4.0
    clk.t += 0.2  # beat 0.8: note 64 is 3.2 beats away: far too early -> ignored, not wrong
    key(p, clk, 64)
    assert p.state()["stop_index"] == 2 and not of(events, "practice_wrong")


def test_wait_mode_completes_song_and_sends_end(env):
    p, clk, events = env
    p.start(SONG, mode="wait", hands=["R", "L"], count_in=True)
    key(p, clk, 60)  # during the count-in: ignored
    assert p.state()["stop_index"] == 0 and not of(events, "practice_wrong")
    clk.t += 5
    p.tick()
    for pitches in ([60, 48], [62], [64, 43], [65]):
        for q in pitches:
            key(p, clk, q)
        for q in pitches:
            key(p, clk, q, on=False)
        clk.t += 3
        p.tick()
    clk.t += 3
    p.tick()
    end = of(events, "practice_end")
    assert end and end[0]["wrong"] == 0 and end[0]["stops"] == 4 and end[0]["mode"] == "wait"


def test_loop_a_part(env):
    p, clk, events = env
    p.start(SONG, mode="watch", hands=["R"], section=1, count_in=False)
    st = p.state()
    assert st["range"] == [4.0, 8.0] and st["anchor_beat"] == 4.0 and st["loop"]
    clk.t += 4.25
    p.tick()
    st = p.state()
    assert st["passes"] == 1 and st["running"] and p.beat_now() == pytest.approx(4.25)
    assert not of(events, "practice_end")


def test_speed_change_keeps_position(env):
    p, clk, events = env
    p.start(SONG, mode="watch", hands=["R"], count_in=False, speed=1.0)
    clk.t += 2
    p.set_speed(0.5)
    assert p.beat_now() == pytest.approx(2.0)
    clk.t += 2
    assert p.beat_now() == pytest.approx(3.0)
    assert p.set_speed(9)["speed"] == 1.5 and p.set_speed(0.01)["speed"] == 0.25


def test_pause_resume_and_hidden_rewind(env):
    p, clk, events = env
    p.start(SONG, mode="watch", hands=["R"], count_in=False)
    clk.t += 3
    s = p.pause(at_beat=2.5, reason="hidden")  # the UI last drew beat 2.5
    assert s["paused"] and s["pause_reason"] == "hidden" and s["beat"] == 2.5
    clk.t += 50
    assert p.beat_now() == 2.5
    p.resume()
    clk.t += 1
    assert p.beat_now() == pytest.approx(3.5)


def test_start_errors(env):
    p, _, _ = env
    with pytest.raises(PracticeError):
        p.start(SONG, mode="dance")
    with pytest.raises(PracticeError):
        p.start(SONG, section=5)
    rh_only = dict(SONG, notes=[n for n in SONG["notes"] if n["hand"] == "R"])
    with pytest.raises(PracticeError):
        p.start(rh_only, hands=["L"])


def test_keyboard_output_plays_other_hand(env):
    p, clk, events = env
    midi = FakeMidi()
    p.midi = midi
    p.start(SONG, mode="wait", hands=["R"], count_in=False, accompany=True, output="keyboard")
    clk.t += 0.01
    p.tick()
    assert midi.sent == []  # the left-hand note at beat 0 waits with the right hand
    key(p, clk, 60)
    clk.t += 0.01
    p.tick()
    assert midi.sent == [(48, 60)]
    p.stop()
    assert midi.sent[-1] == (48, 0)  # all notes off


def test_watch_keyboard_output_all_notes(env):
    p, clk, events = env
    midi = FakeMidi()
    p.midi = midi
    p.start(SONG, mode="watch", hands=["R"], count_in=False, output="keyboard")
    for _ in range(90):
        clk.t += 0.1
        p.tick()
    ons = [n for n, v in midi.sent if v > 0]
    offs = [n for n, v in midi.sent if v == 0]
    assert ons == [60, 48, 62, 64, 43, 65] and sorted(offs) == sorted(ons)


@pytest.mark.parametrize("sid", ["mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle",
                                 "au-clair-de-la-lune", "frere-jacques", "london-bridge"])
def test_builtin_song_completes_in_wait_mode(env, sid):
    """A fake player that presses each expected key when the song waits completes each song."""
    p, clk, events = env
    song = songs.get(sid)
    hands = songs.hands_of(song)
    p.start(song, mode="wait", hands=hands, count_in=True, speed=1.5)
    for _ in range(100000):
        clk.t += 0.01
        p.tick()
        st = p.state()
        if st["done"]:
            break
        if st["waiting"]:
            for e in st["expected"]:
                key(p, clk, e["pitch"])
            for e in st["expected"]:
                key(p, clk, e["pitch"], on=False)
    end = of(events, "practice_end")
    assert end and end[0]["wrong"] == 0
    assert end[0]["stops"] == len({n["start"] for n in song["notes"]})


def test_pause_for_an_old_run_is_ignored(env):
    p, clk, events = env
    first = p.start(SONG, mode="watch", hands=["R"], count_in=False)
    p.start(SONG, mode="watch", hands=["R"], count_in=False)
    assert not p.pause(run=first["run"], reason="left")["paused"]  # crossed with the new start
    assert p.pause(run=first["run"] + 1)["paused"]


def test_keyboard_output_records_sends_for_the_echo_guard(env):
    """Practice tells the echo guard about each song note that it sends to the keyboard."""
    p, clk, events = env
    p.midi = FakeMidi()
    p.start(SONG, mode="watch", hands=["R"], count_in=False, output="keyboard")
    clk.t += 0.01
    p.tick()  # sends 60 and 48 at beat 0
    assert p.echo.is_echo(True, 0, 60, clk.t) and p.echo.is_echo(True, 0, 48, clk.t)
    assert p.echo.is_echo(False, 0, 60, clk.t + 0.5)  # the echo's note off
    assert not p.echo.is_echo(True, 0, 60, clk.t + 0.5)  # later: a real press


def test_hit_and_wrong_events_name_the_song_and_run(env):
    p, clk, events = env
    st = p.start(SONG, mode="wait", hands=["R"], count_in=False)
    key(p, clk, 61)
    key(p, clk, 61, on=False)
    key(p, clk, 60)
    wrong, hit = of(events, "practice_wrong")[0], of(events, "practice_hit")[0]
    for e in (wrong, hit):
        assert e["song_id"] == "t" and e["run"] == st["run"]


def test_start_errors_are_plain_sentences(env):
    p, _, _ = env
    for kwargs in ({"mode": "dance"}, {"section": 5}, {"section": True}, {"hands": 5}, {"hands": [1]},
                   {"output": ["x"]}):
        with pytest.raises(PracticeError) as exc:
            p.start(SONG, **kwargs)
        text = str(exc.value)
        assert text[0].isupper() and text.endswith("."), text
