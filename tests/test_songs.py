"""Built-in songs (PLAN 5.1, 5.4, 8.3 Levels 1-3): format, fingering, hand positions, words."""

import json
import re
from pathlib import Path

import pytest

from riyaz import songs
from riyaz.songs import SongError, position_keys, validate

ROOT = Path(__file__).resolve().parent.parent
BUILTIN = {
    "mary-had-a-little-lamb": 1, "ode-to-joy": 1, "twinkle-twinkle": 1,
    "au-clair-de-la-lune": 2, "frere-jacques": 2, "london-bridge": 2,
    "ode-to-joy-left-hand": 3, "twinkle-twinkle-left-hand": 3, "frere-jacques-both-hands": 3,
}
# Words that a Level 1-2 user has not learned yet (PLAN 7.4).
LOCKED = re.compile(r"\b(bar|bars|measure|tempo|beat|beats|chord|chords|rest|rests|scale|interval|"
                    r"major|minor|sharp|flat|progression)\b", re.I)


def builtin():
    return {sid: s for sid, s in songs.load_all().items() if sid in BUILTIN}


def test_nine_builtin_songs_load():
    got = builtin()
    assert set(got) == set(BUILTIN)
    for sid, level in BUILTIN.items():
        assert got[sid]["level"] == level
    assert len(list((ROOT / "data" / "songs").glob("*.json"))) == 9


def _position_at(song, hand, beat):
    pos = None
    for p in song["hand_positions"]:
        if p["hand"] == hand and p["start"] <= beat + 1e-9:
            pos = p
    return pos


@pytest.mark.parametrize("sid", sorted(BUILTIN))
def test_fingering_matches_hand_position(sid):
    """Each note has a finger, and the hand position puts that finger on that key."""
    song = builtin()[sid]
    for n in song["notes"]:
        assert n["finger"] in (1, 2, 3, 4, 5), n
        pos = _position_at(song, n["hand"], n["start"])
        assert pos is not None, f"no hand position for {n}"
        keys = position_keys(pos)
        assert keys[n["finger"] - 1] == n["pitch"], (sid, n, keys)


@pytest.mark.parametrize("sid", sorted(BUILTIN))
def test_song_shape(sid):
    song = builtin()[sid]
    assert song["source"] == "builtin" and "public domain" in song["credit"]
    for n in song["notes"]:
        assert (n["start"] * 2).is_integer() and (n["dur"] * 2).is_integer()  # half beats
        assert 36 <= n["pitch"] <= 96
        assert n["pitch"] % 12 not in (1, 3, 6, 8, 10), "Level 1-3: white keys only"
    # One hand plays one note at a time (no keys together before Level 5), with no overlap.
    for hand in songs.hands_of(song):
        hn = [n for n in song["notes"] if n["hand"] == hand]
        for a, b in zip(hn, hn[1:]):
            assert a["start"] + a["dur"] <= b["start"] + 1e-9, (a, b)
    # Parts cover the song, in order, with plain names.
    secs = song["sections"]
    assert secs[0]["start"] == 0 and secs[-1]["end"] == song["end"]
    for i, (a, b) in enumerate(zip(secs, secs[1:])):
        assert a["end"] == b["start"]
    assert [s["name"] for s in secs] == [f"Part {i + 1}" for i in range(len(secs))]
    assert song["end"] % song["time_signature"][0] == 0
    assert songs.hands_of(song) == (["L"] if sid.endswith("-left-hand") else ["R", "L"] if sid.endswith("-both-hands")
                                    else songs.hands_of(song))
    assert not LOCKED.search(song["title"] + " " + " ".join(s["name"] for s in secs))


def test_melodies_start_correctly():
    """A short check of the well-known first notes (C4 = 60)."""
    first = {
        "mary-had-a-little-lamb": [64, 62, 60, 62, 64, 64, 64],
        "ode-to-joy": [64, 64, 65, 67, 67, 65, 64, 62, 60, 60, 62, 64],
        "twinkle-twinkle": [60, 60, 67, 67, 69, 69, 67],
        "au-clair-de-la-lune": [65, 65, 65, 67, 69, 67],  # in F
        "frere-jacques": [60, 62, 64, 60, 60, 62, 64, 60, 64, 65, 67],
        "london-bridge": [67, 69, 67, 65, 64, 65, 67],
    }
    # Level 3: the left hand plays the same melodies, one octave lower.
    for sid in ("ode-to-joy", "twinkle-twinkle"):
        left = sorted((n for n in builtin()[f"{sid}-left-hand"]["notes"]), key=lambda n: n["start"])
        right = sorted((n for n in builtin()[sid]["notes"] if n["hand"] == "R"), key=lambda n: n["start"])
        assert [(n["pitch"] + 12, n["start"], n["dur"]) for n in left] == [(n["pitch"], n["start"], n["dur"]) for n in right]
    both = builtin()["frere-jacques-both-hands"]
    assert [n for n in both["notes"] if n["hand"] == "R"] == [
        {**n, "id": m["id"]} for n, m in zip([x for x in builtin()["frere-jacques"]["notes"] if x["hand"] == "R"],
                                             [x for x in both["notes"] if x["hand"] == "R"])]
    # Rhythm of the first phrase, in counts (1 = one click). The notes follow each other (no gap).
    rhythm = {
        "mary-had-a-little-lamb": [1, 1, 1, 1, 1, 1, 2],
        "ode-to-joy": [1] * 12 + [1.5, 0.5, 2],
        "twinkle-twinkle": [1, 1, 1, 1, 1, 1, 2],
        "au-clair-de-la-lune": [1, 1, 1, 1, 2, 2],
        "frere-jacques": [1] * 10 + [2],
        "london-bridge": [1.5, 0.5, 1, 1, 1, 1, 2],
    }
    for sid, pitches in first.items():
        notes = sorted((n for n in builtin()[sid]["notes"] if n["hand"] == "R"), key=lambda n: n["start"])
        assert [n["pitch"] for n in notes[: len(pitches)]] == pitches, sid
        durs = rhythm[sid]
        assert [n["dur"] for n in notes[: len(durs)]] == durs, sid
        t = notes[0]["start"]
        for n, d in zip(notes, durs):
            assert n["start"] == pytest.approx(t), (sid, n)
            t += d


def test_summaries_sorted_by_level_then_order():
    summ = [s for s in songs.list_summaries() if s["id"] in BUILTIN]
    assert [s["id"] for s in summ] == ["mary-had-a-little-lamb", "ode-to-joy", "twinkle-twinkle",
                                      "au-clair-de-la-lune", "frere-jacques", "london-bridge",
                                      "ode-to-joy-left-hand", "twinkle-twinkle-left-hand", "frere-jacques-both-hands"]
    mary = summ[0]
    assert mary["hands"] == ["R"] and mary["beats"] == 32 and mary["seconds"] == round(32 * 60 / 90)
    assert summ[3]["hands"] == ["R", "L"]


def _base():
    return {"id": "t", "title": "T", "bpm": 100, "notes": [{"pitch": 60, "start": 0, "dur": 1, "hand": "R"}]}


@pytest.mark.parametrize("change", [
    {"id": "Bad Id"}, {"bpm": 5}, {"notes": []}, {"level": 0},
    {"notes": [{"pitch": 20, "start": 0, "dur": 1, "hand": "R"}]},
    {"notes": [{"pitch": 60, "start": -1, "dur": 1, "hand": "R"}]},
    {"notes": [{"pitch": 60, "start": 0, "dur": 0, "hand": "R"}]},
    {"notes": [{"pitch": 60, "start": 0, "dur": 1, "hand": "X"}]},
    {"notes": [{"pitch": 60, "start": 0, "dur": 1, "hand": "R", "finger": 6}]},
    {"sections": [{"name": "Part 1", "start": 4, "end": 2}]},
    {"hand_positions": [{"hand": "R", "start": 0, "thumb_pitch": 60, "keys": [60, 59, 62, 64, 65]}]},
])
def test_validate_rejects_bad_songs(change):
    raw = _base()
    raw.update(change)
    with pytest.raises(SongError):
        validate(raw)


def test_white_keys_from():
    assert songs.white_keys_from(60, "R") == [60, 62, 64, 65, 67]
    assert songs.white_keys_from(48, "L") == [48, 47, 45, 43, 41]


def test_extra_song_dir_and_bad_file_skipped(tmp_path, monkeypatch):
    (tmp_path / "bad.json").write_text("{not json")
    good = _base() | {"id": "extra-song"}
    (tmp_path / "extra.json").write_text(json.dumps(good))
    monkeypatch.setenv("RIYAZ_EXTRA_SONG_DIR", str(tmp_path))
    all_ = songs.load_all()
    assert "extra-song" in all_ and set(BUILTIN) <= set(all_)
