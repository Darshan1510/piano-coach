"""Automatic fingering (PLAN 5.3) and hand split (PLAN 5.2)."""

from pathlib import Path

import pytest

from riyaz import fingering, handsplit, songs
from riyaz.importers import midi_import as mi
from tools.fingering_report import black_key_set, report

MIDI = Path(__file__).resolve().parent / "data" / "midi"


def test_fingering_matches_hand_written_fingering():
    """PLAN 5.3 acceptance: at least 70% of the notes of the built-in songs (Levels 1-3, 9 songs)."""
    r = report(beginner=True)
    for sid, (a, b) in r["songs"].items():
        print(f"{sid}: {a}/{b} = {a / b:.1%}")
    print(f"all: {r['same']}/{r['total']} = {r['ratio']:.1%}")
    assert r["total"] == 350 and len(r["songs"]) == 9
    assert r["ratio"] >= 0.70
    assert min(a / b for a, b in r["songs"].values()) >= 0.6


def test_normal_mode_matches_hand_written_fingering():
    """Normal mode (imported songs with black keys, Levels 4+): at least 70% of the notes of the
    built-in songs and of the black-key set (scales in G/D/F, Ode to Joy in D, triads) with
    standard textbook fingering, each alone and together."""
    a = report(beginner=False)
    b = report(beginner=False, extra=True)
    for r in (a, b):
        for sid, (same, total) in r["songs"].items():
            print(f"{sid}: {same}/{total} = {same / total:.1%}")
    assert len(b["songs"]) == 4 and b["total"] == 144
    assert all(any(fingering.theory.is_black(n["pitch"]) for n in s["notes"]) for s in black_key_set())
    assert a["ratio"] >= 0.70 and b["ratio"] >= 0.70
    assert (a["same"] + b["same"]) / (a["total"] + b["total"]) >= 0.70
    assert b["songs"]["triads"][0] == b["songs"]["triads"][1]  # 1 3 5 / 5 3 1 on every triad


def test_black_key_set_is_valid():
    """Each passage: fingers 1-5, keys together have fingers in hand order, one hand per onset."""
    for s in black_key_set():
        by_start = {}
        for n in s["notes"]:
            assert 1 <= n["finger"] <= 5 and n["hand"] in ("R", "L")
            by_start.setdefault((n["start"], n["hand"]), []).append(n)
        for (_t, hand), g in by_start.items():
            fs = [n["finger"] for n in sorted(g, key=lambda n: n["pitch"])]
            assert fs == (sorted(fs) if hand == "R" else sorted(fs, reverse=True))


def _n(pitch, start, dur=1.0, hand="R"):
    return {"pitch": pitch, "start": float(start), "dur": dur, "hand": hand, "finger": None}


def test_beginner_mode_five_finger_position():
    notes = [_n(p, i) for i, p in enumerate([60, 62, 64, 65, 67, 65, 64, 62, 60])]
    r = fingering.finger_song(notes)
    assert r["modes"] == {"R": "beginner"}
    assert [n["finger"] for n in notes] == [1, 2, 3, 4, 5, 4, 3, 2, 1]
    assert r["hand_positions"] == [{"hand": "R", "start": 0.0, "thumb_pitch": 60}]


def test_beginner_mode_left_hand_mirrors():
    notes = [_n(p, i, hand="L") for i, p in enumerate([48, 47, 45, 43, 41])]
    fingering.finger_song(notes)
    assert [n["finger"] for n in notes] == [1, 2, 3, 4, 5]


def test_beginner_mode_few_position_changes():
    # C D E F G then A B C: one move, not a move on each note.
    notes = [_n(p, i) for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72, 71, 69])]
    r = fingering.finger_song(notes)
    thumbs = [p["thumb_pitch"] for p in r["hand_positions"]]
    assert len(thumbs) == 2


def test_black_keys_use_normal_mode_and_no_thumb_on_black_when_avoidable():
    notes = [_n(p, i * 0.5) for i, p in enumerate([62, 64, 66, 67, 69, 71, 73, 74])]  # D major up
    r = fingering.finger_song(notes)
    assert r["modes"] == {"R": "normal"}
    assert all(not (n["finger"] == 1 and n["pitch"] in (66, 73)) for n in notes)
    # An 8-key walk needs the thumb to go under once: fingers go 1 2 3 1 2 3 4 5 (or similar).
    assert sorted({n["finger"] for n in notes}) == [1, 2, 3, 4, 5]


def test_chord_fingers_are_ordered():
    notes = [_n(60, 0), _n(64, 0), _n(67, 0), _n(65, 1), _n(69, 1), _n(72, 1)]
    fingering.finger_song(notes, beginner=False)
    a = [n["finger"] for n in notes[:3]]
    b = [n["finger"] for n in notes[3:]]
    assert a == sorted(a) and len(set(a)) == 3 and b == sorted(b) and len(set(b)) == 3
    left = [_n(48, 0, hand="L"), _n(52, 0, hand="L"), _n(55, 0, hand="L")]
    fingering.finger_song(left, beginner=False)
    assert [n["finger"] for n in left] == [5, 3, 1]


def test_hand_positions_cover_every_note():
    for song in songs.load_all().values():
        notes = [dict(n, finger=None) for n in song["notes"]]
        r = fingering.finger_song(notes)
        for n in notes:
            pos = [p for p in r["hand_positions"] if p["hand"] == n["hand"] and p["start"] <= n["start"]]
            assert songs.position_keys(pos[-1])[n["finger"] - 1] == n["pitch"]


@pytest.mark.parametrize("name", ["bach-minuet-a-minor-bwv-anh-120.mid", "la-native.mid", "les-graces.mid"])
def test_dp_hand_split_agrees_with_the_two_tracks(name):
    """1-track split (DP) vs the real right/left tracks of the same file."""
    parsed = mi.parse((MIDI / name).read_bytes(), name)
    two = mi.build_song(parsed)
    truth = {(n["start"], n["pitch"]): n["hand"] for n in two["notes"]}
    merged = mi.Part(index=0, track=0, channel=0, name="all", instrument="Piano", program=None,
                     notes=sorted(x for p in parsed.parts for x in p.notes))
    parsed.parts = [merged]
    one = mi.build_song(parsed, parts=[0])
    same = sum(1 for n in one["notes"] if truth.get((n["start"], n["pitch"])) == n["hand"])
    print(f"{name}: {same}/{len(one['notes'])}")
    assert same / len(one["notes"]) >= 0.9


def test_dp_split_rules():
    # Far apart: low notes left, high notes right, also when they come one at a time.
    notes = [_n(p, i) for i, p in enumerate([40, 76, 43, 79, 45, 81])]
    handsplit.split_dp(notes)
    assert [n["hand"] for n in notes] == ["L", "R", "L", "R", "L", "R"]
    # A melody that goes below middle C a little stays in the right hand (hands stay continuous).
    mel = [_n(p, i) for i, p in enumerate([64, 62, 60, 59, 57, 59, 60, 62])]
    bass = [_n(36, 0, 8.0)]
    handsplit.split_dp(mel + bass)
    assert all(n["hand"] == "R" for n in mel) and bass[0]["hand"] == "L"
    # More than an octave at once is split between the hands.
    wide = [_n(p, 0) for p in (48, 55, 64, 67, 72)]
    handsplit.split_dp(wide)
    lo = [n["pitch"] for n in wide if n["hand"] == "L"]
    hi = [n["pitch"] for n in wide if n["hand"] == "R"]
    assert lo and hi and max(lo) < min(hi) and max(hi) - min(hi) <= 12


def test_two_parts_and_swap():
    a, b = [_n(72, 0)], [_n(48, 0)]
    assert handsplit.assign_hands([a, b]) == "parts"
    assert a[0]["hand"] == "R" and b[0]["hand"] == "L"
    handsplit.assign_hands([a, b], swap=True)
    assert a[0]["hand"] == "L" and b[0]["hand"] == "R"
