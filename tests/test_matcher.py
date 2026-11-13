"""Wait-mode matcher (PLAN 6.4). No clock, no MIDI."""

import pytest

from riyaz import songs
from riyaz.matcher import WaitMatcher, build_stops

SONG = {
    "notes": [
        {"pitch": 60, "start": 0.0, "dur": 1, "hand": "R"},
        {"pitch": 48, "start": 0.0, "dur": 4, "hand": "L"},
        {"pitch": 64, "start": 1.0, "dur": 1, "hand": "R"},
        {"pitch": 67, "start": 1.0, "dur": 1, "hand": "R"},
        {"pitch": 64, "start": 2.0, "dur": 1, "hand": "R"},
        {"pitch": 43, "start": 4.0, "dur": 4, "hand": "L"},
    ]
}


def test_stops_per_hand():
    assert [sorted(s.pitches) for s in build_stops(SONG, ["R"])] == [[60], [64, 67], [64]]
    assert [sorted(s.pitches) for s in build_stops(SONG, ["L"])] == [[48], [43]]
    both = build_stops(SONG, ["R", "L"])
    assert [s.beat for s in both] == [0.0, 1.0, 2.0, 4.0] and sorted(both[0].pitches) == [48, 60]
    assert [s.beat for s in build_stops(SONG, ["R"], start=1.0, end=2.0)] == [1.0]


def test_single_note_advances_and_repeat_needs_new_press():
    m = WaitMatcher.for_song(SONG, ["R"])
    assert m.press(60, 0.0)["advanced"]
    # keys together: both down -> advance, even with a long gap between the presses
    assert not m.press(64, 1.0)["advanced"]
    assert m.press(67, 3.0)["advanced"]
    # the next stop is 64 again: the key that is still down does not count; press it again
    assert m.current.beat == 2.0
    m.release(64, 3.1)
    assert m.press(64, 3.2)["advanced"]
    assert m.done and m.press(60, 4.0)["result"] == "done"


def test_in_order_within_300ms():
    m = WaitMatcher.for_song(SONG, ["R"], start=1.0)
    m.press(64, 10.0)
    m.release(64, 10.05)
    assert m.press(67, 10.25)["advanced"]  # 250 ms after, first key already up: OK


def test_in_order_too_slow_does_not_advance():
    m = WaitMatcher.for_song(SONG, ["R"], start=1.0)
    m.press(64, 10.0)
    m.release(64, 10.05)
    assert not m.press(67, 10.4)["advanced"]  # 400 ms: too slow, first key is up
    m.release(67, 10.45)
    assert m.press(64, 10.6)["advanced"]  # 64 again, 200 ms after 67: OK


def test_wrong_key_logged_and_no_advance():
    m = WaitMatcher.for_song(SONG, ["R"])
    r = m.press(62, 1.0, beat=0.0)
    assert r["result"] == "wrong" and not r["advanced"] and r["expected"] == [60]
    assert m.index == 0 and m.errors == [{"stop": 0, "pitch": 62, "expected": [60], "t": 1.0, "beat": 0.0}]
    assert m.press(60, 1.5)["advanced"]


def test_reset_for_loop():
    m = WaitMatcher.for_song(SONG, ["L"])
    m.press(48, 0)
    m.press(43, 1)
    assert m.done
    m.reset()
    assert m.index == 0 and m.current.beat == 0.0


@pytest.mark.parametrize("sid", ["mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle",
                                 "au-clair-de-la-lune", "frere-jacques", "london-bridge"])
def test_every_builtin_song_completes_for_each_hand_choice(sid):
    song = songs.get(sid)
    for hands in (["R"], ["L"], ["R", "L"]):
        if not set(hands) <= set(songs.hands_of(song)):
            continue
        m = WaitMatcher.for_song(song, hands)
        t = 0.0
        while not m.done:
            stop = m.current
            for p in sorted(stop.pitches):
                assert m.press(p, t)["result"] == "hit"
            for p in stop.pitches:
                m.release(p, t + 0.1)
            t += 0.5
        assert m.errors == []
        assert len(m.stops) == len({n["start"] for n in song["notes"] if n["hand"] in hands})
