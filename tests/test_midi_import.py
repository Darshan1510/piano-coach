"""MIDI import (PLAN 11.1): reading, tracks, beats, edge cases, bad files, saving."""

import json
import random
import warnings
from pathlib import Path

import mido
import pytest

from riyaz import config, songs
from riyaz.importers import midi_import as mi
from riyaz.matcher import WaitMatcher

MIDI = Path(__file__).resolve().parent / "data" / "midi"
SYN = MIDI / "synthetic"
PUBLIC_DOMAIN = ["bach-minuet-a-minor-bwv-anh-120.mid", "la-native.mid", "les-graces.mid"]
ALL_FILES = sorted(MIDI.glob("*.mid")) + sorted(SYN.glob("*.mid"))


def load(path: Path, **kw) -> dict:
    data = path.read_bytes()
    return mi.build_song(mi.parse(data, path.name), **kw)


def play_wait(song: dict, hands) -> WaitMatcher:
    m = WaitMatcher.for_song(song, hands)
    t = 0.0
    while not m.done:
        stop = m.current
        for p in stop.pitches:
            m.press(p, t)
        for p in stop.pitches:
            m.release(p, t + 0.01)
        t += 0.5
    return m


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_test_file_imports_and_completes_wait_mode(path, data_dir):
    song = load(path)
    assert song["source"] == "midi" and song["notes"]
    assert all(config.KEY_LOW <= n["pitch"] <= config.KEY_HIGH for n in song["notes"])
    assert all(n["finger"] in (1, 2, 3, 4, 5) for n in song["notes"])
    for hands in ([h] for h in songs.hands_of(song)):
        assert not play_wait(song, hands).errors
    assert not play_wait(song, songs.hands_of(song)).errors
    # Each finger is on the key of its hand position at that time (same rule as built-in songs).
    for n in song["notes"]:
        pos = [p for p in song["hand_positions"] if p["hand"] == n["hand"] and p["start"] <= n["start"] + 1e-6]
        assert pos, n
        assert songs.position_keys(pos[-1])[n["finger"] - 1] == n["pitch"], n
    # At most 5 keys at once in one hand, different fingers.
    groups = {}
    for n in song["notes"]:
        groups.setdefault((n["hand"], n["start"]), []).append(n["finger"])
    assert all(len(f) <= 5 and len(set(f)) == len(f) for f in groups.values())
    assert song["sections"] and song["sections"][0]["name"] == "Part 1"
    assert song["sections"][-1]["end"] >= song["end"] - 1e-6


def test_public_domain_files_two_tracks_and_one_track():
    for name in PUBLIC_DOMAIN:
        tracks = mi.track_list(mi.parse((MIDI / name).read_bytes(), name))
        assert len(tracks) == 2 and all(t["default"] and not t["drums"] for t in tracks)
    one = mi.track_list(mi.parse((MIDI / "les-graces-one-track.mid").read_bytes(), "x.mid"))
    assert len(one) == 1 and one[0]["note_count"] == 228
    song = load(MIDI / "les-graces-one-track.mid")
    assert song["import"]["method"] == "split" and songs.hands_of(song) == ["R", "L"]


def test_track_list_has_counts_and_instruments():
    tracks = mi.track_list(mi.parse((SYN / "drums.mid").read_bytes(), "drums.mid"))
    by_name = {t["name"]: t for t in tracks}
    assert by_name["Piano"]["default"] and by_name["Piano"]["instrument"] == "Piano"
    assert by_name["Piano"]["note_count"] == 12
    assert by_name["Drums"]["drums"] and not by_name["Drums"]["default"] and by_name["Drums"]["channel"] == 10
    assert by_name["Bass"]["instrument"] == "Bass" and not by_name["Bass"]["default"]
    song = load(SYN / "drums.mid")  # default = the piano track only
    assert len(song["notes"]) == 12


def test_beats_match_music21():
    """Dev-only oracle (music21, DECISIONS.md): note starts and lengths in quarter notes."""
    music21 = pytest.importorskip("music21")
    for name in PUBLIC_DOMAIN:
        song = load(MIDI / name)
        num, den = song["time_signature"]
        factor = den / 4
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            score = music21.converter.parse(str(MIDI / name), quantizePost=False).stripTies()
        theirs = sorted((round(float(n.offset), 3), p.midi) for n in score.flatten().notes for p in n.pitches)
        first = theirs[0][0]
        bar_q = num / factor
        shift = (first // bar_q) * bar_q
        # The same key at the same time in both hands is one key press (the app keeps one note).
        theirs = sorted({(round(o - shift, 3), p) for o, p in theirs})
        ours = sorted((round(n["start"] / factor, 3), n["pitch"]) for n in song["notes"])
        assert ours == theirs, name
        bpm_q = float(score.metronomeMarkBoundaries()[0][2].number)
        assert abs(song["bpm"] / factor - bpm_q) < 0.6, name


def test_tempo_changes_counted_main_tempo_used():
    song = load(SYN / "tempo-changes.mid")
    assert song["bpm"] == 100 and song["import"]["tempo_changes"] == 2
    assert song["time_signature"] == [4, 4]
    assert song["import"]["method"] == "parts"
    assert {n["hand"] for n in song["notes"] if n["pitch"] < 55} == {"L"}


def test_six_eight_uses_eighth_note_beats():
    song = load(MIDI / "la-native.mid")
    assert song["time_signature"] == [6, 8]
    assert song["bpm"] == pytest.approx(182.0, abs=0.1)  # 91 quarter notes a minute = 182 eighths
    assert song["sections"][0] == {"name": "Part 1", "start": 0.0, "end": 24.0}  # 4 bars of 6


def test_vel0_note_off_and_one_track_split():
    song = load(SYN / "one-track-vel0.mid")
    assert len(song["notes"]) == 16
    assert all(n["hand"] == ("L" if n["pitch"] < 55 else "R") for n in song["notes"])
    assert song["import"]["fingering"] == {"R": "beginner", "L": "beginner"}
    right = [n["finger"] for n in song["notes"] if n["hand"] == "R"]
    assert right[:5] == [1, 2, 3, 4, 5]


def test_empty_tracks_out_of_range_retrigger_and_no_note_off():
    tracks = mi.track_list(mi.parse((SYN / "empty-tracks.mid").read_bytes(), "e.mid"))
    assert len(tracks) == 1 and tracks[0]["name"] == "Melody"
    song = load(SYN / "empty-tracks.mid")
    assert song["import"]["moved_octave"] == 2  # 100 -> 88, 24 -> 36
    pitches = [n["pitch"] for n in song["notes"]]
    assert 88 in pitches and 36 in pitches
    d = [n for n in song["notes"] if n["pitch"] == 62]
    assert len(d) == 2 and d[0]["dur"] == pytest.approx(1.0)  # pressed again: the first note ends
    assert any(n["pitch"] == 65 for n in song["notes"])  # no note off: ends at the track end


def test_quantize_moves_starts_to_the_grid():
    path = SYN / "one-track-vel0.mid"
    m = mido.MidiFile(path)
    # Move each note a little (a "messy" file), then import with the 1/8 and 1/16 grid.
    rnd = random.Random(1)
    for tr in m.tracks:
        for msg in tr:
            if msg.time:
                msg.time = max(0, msg.time + rnd.randint(-30, 30))
    import io
    buf = io.BytesIO()
    m.save(file=buf)
    parsed = mi.parse(buf.getvalue(), "messy.mid")
    for q, grid in ((8, 0.5), (16, 0.25)):
        song = mi.build_song(parsed, quantize=q)
        assert all(abs(n["start"] / grid - round(n["start"] / grid)) < 1e-6 for n in song["notes"])
        assert all(n["dur"] >= grid - 1e-6 for n in song["notes"])
    with pytest.raises(mi.MidiImportError):
        mi.build_song(parsed, quantize=3)


def test_keys_together_and_chords_detected():
    song = load(SYN / "chords-one-track.mid")
    left = [n for n in song["notes"] if n["hand"] == "L"]
    assert len(left) == 12  # the 3-key groups are in the left hand
    assert [c["name"] for c in song["chords"]][1:] == ["F", "G", "C"]
    assert "keys_together" in song["difficulty"]["skills"] and song["level"] == 5
    assert song["key"] == "C major"


def test_sections_split_at_long_pause():
    notes = [{"start": 0.0, "dur": 1.0, "pitch": 60}, {"start": 4.0, "dur": 1.0, "pitch": 62},
             {"start": 12.0, "dur": 1.0, "pitch": 64}]  # a pause of 7 beats (> 1 bar of 4)
    parts = mi.detect_sections(notes, 4.0, 13.0)
    assert [(p["start"], p["end"]) for p in parts] == [(0.0, 12.0), (12.0, 16.0)]
    long = [{"start": float(i), "dur": 1.0, "pitch": 60} for i in range(40)]
    parts = mi.detect_sections(long, 4.0, 40.0)
    assert [p["end"] - p["start"] for p in parts] == [16.0, 16.0, 8.0]
    assert [p["name"] for p in parts] == ["Part 1", "Part 2", "Part 3"]


BAD = {
    "empty": b"",
    "not midi": b"hello, this is text and not a MIDI file",
    "header only": b"MThd\x00\x00\x00\x06\x00\x01\x00\x02\x01\xe0",
    "truncated": (MIDI / "la-native.mid").read_bytes()[:300],
    "garbage after header": b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x01\xe0MTrk\xff\xff\xff\xff" + bytes(range(256)),
    "zero division": b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x00\x00MTrk\x00\x00\x00\x04\x00\xff\x2f\x00",
}


@pytest.mark.parametrize("name", list(BAD))
def test_bad_files_give_a_clear_error(name):
    with pytest.raises(mi.MidiImportError) as err:
        mi.build_song(mi.parse(BAD[name], "bad.mid"))
    text = str(err.value)
    assert text[0].isupper() and text.endswith(".") and "Traceback" not in text


def test_random_damage_never_crashes():
    good = (MIDI / "les-graces.mid").read_bytes()
    rnd = random.Random(7)
    for _ in range(300):
        b = bytearray(good)
        for _ in range(rnd.randint(1, 40)):
            b[rnd.randrange(14, len(b))] = rnd.randrange(256)
        if rnd.random() < 0.3:
            b = b[: rnd.randrange(14, len(b))]
        try:
            song = mi.build_song(mi.parse(bytes(b), "x.mid"))
        except mi.MidiImportError:
            continue
        songs.validate(song)  # a song that imports is a correct song


def test_file_size_and_note_limits(monkeypatch):
    with pytest.raises(mi.MidiImportError, match="too large"):
        mi.parse(b"MThd" + b"\0" * config.IMPORT_MAX_BYTES, "big.mid")
    # The user limit is for the selected tracks (in build_song), not for the file.
    monkeypatch.setattr(config, "IMPORT_MAX_NOTES", 50)
    parsed = mi.parse((MIDI / "les-graces.mid").read_bytes(), "x.mid")
    with pytest.raises(mi.MidiImportError, match="too many notes"):
        mi.build_song(parsed)
    # The raw limit (memory) is for the file.
    monkeypatch.setattr(config, "IMPORT_MAX_RAW_NOTES", 50)
    with pytest.raises(mi.MidiImportError, match="too many notes"):
        mi.parse((MIDI / "les-graces.mid").read_bytes(), "x.mid")


# ---------------------------------------------------------------- review fixes (Phase 3)


def _midi(tracks, tpb=480, mtype=1) -> bytes:
    """tracks = [[(tick, msg), ...]] -> MIDI file bytes."""
    import io
    mid = mido.MidiFile(type=mtype, ticks_per_beat=tpb)
    for events in tracks:
        tr = mido.MidiTrack()
        last = 0
        for tick, msg in events:
            tr.append(msg.copy(time=tick - last))
            last = tick
        tr.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(tr)
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def _scale(n=16, ch=0, step=240, start=0, pitch0=60):
    ev = []
    for i in range(n):
        t = start + i * step
        ev.append((t, mido.Message("note_on", note=pitch0 + (i % 8), velocity=80, channel=ch)))
        ev.append((t + step - 10, mido.Message("note_off", note=pitch0 + (i % 8), velocity=0, channel=ch)))
    return ev


@pytest.mark.parametrize("ts,qpm,want_ts,bar_quarters", [
    ((6, 8), 180, [3, 4], 3),    # 360 eighths a minute is too fast: quarter-note beat, 3 beats a bar
    ((6, 8), 100, [6, 8], 3),    # 200 eighths a minute: the eighth note is the beat
    ((2, 2), 30, [4, 4], 4),     # 15 half notes a minute is too slow: quarter-note beat
    ((2, 2), 100, [2, 2], 4),    # 50 half notes a minute: the half note is the beat
    ((3, 8), 180, [3, 8], 1.5),  # no beat fits: the time signature stays, the speed is clamped to 300
    ((3, 4), 120, [3, 4], 3),
])
def test_time_signature_and_bar_stay_consistent(ts, qpm, want_ts, bar_quarters, data_dir):
    tempo = mido.bpm2tempo(qpm)
    meta = [(0, mido.MetaMessage("set_tempo", tempo=tempo)),
            (0, mido.MetaMessage("time_signature", numerator=ts[0], denominator=ts[1]))]
    # First note in the second bar: the song starts at that bar (bar length check).
    first = int(bar_quarters * 480)
    data = _midi([meta + _scale(start=first)])
    song = mi.build_song(mi.parse(data, "ts.mid"))
    assert song["time_signature"] == want_ts
    num, den = song["time_signature"]
    beats_per_quarter = den / 4
    assert 20 <= song["bpm"] <= 300
    if (ts, qpm) != ((3, 8), 180):
        assert song["bpm"] == pytest.approx(qpm * beats_per_quarter, abs=0.01)
    # One bar of the song = num beats = the bar of the file.
    assert num / beats_per_quarter == pytest.approx(bar_quarters)
    assert song["notes"][0]["start"] == 0  # the shift was exactly one bar
    for sec in song["sections"]:
        assert (sec["start"] / num) == pytest.approx(round(sec["start"] / num))


def test_tempo_at_the_same_tick_later_event_wins():
    # Track 0 sets 100 then 60 at tick 0; track 1 sets 140 at tick 0 (later track = later event).
    t0 = [(0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100))),
          (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60)))]
    parsed = mi.parse(_midi([t0, _scale()]), "t.mid")
    assert mi.main_tempo(parsed)[0] == mido.bpm2tempo(60)  # 60 has the smaller tuple, 60 is last: both agree
    t0 = [(0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60))),
          (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100)))]
    parsed = mi.parse(_midi([t0, _scale()]), "t.mid")
    assert mi.main_tempo(parsed)[0] == mido.bpm2tempo(100)  # a sort on (tick, tempo) gave 60
    t1 = [(0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(140)))] + _scale()
    parsed = mi.parse(_midi([t0, t1]), "t.mid")
    assert mi.main_tempo(parsed)[0] == mido.bpm2tempo(140)


def test_drums_and_other_tracks_do_not_count_for_the_note_limit(monkeypatch):
    monkeypatch.setattr(config, "IMPORT_MAX_NOTES", 40)
    drums = [(i * 60, mido.Message("note_on", note=36, velocity=90, channel=9)) for i in range(200)]
    strings = [(0, mido.Message("program_change", program=48, channel=1))] + _scale(n=100, ch=1, step=60)
    piano = _scale(n=24, ch=0)
    data = _midi([piano, drums, strings])
    parsed = mi.parse(data, "pop.mid")  # 324 notes in the file: no error
    tracks = mi.track_list(parsed)
    assert [t["note_count"] for t in tracks] == [24, 200, 100]
    song = mi.build_song(parsed)  # default = the piano track
    assert len(song["notes"]) == 24
    with pytest.raises(mi.MidiImportError, match="too many notes"):
        mi.build_song(parsed, parts=[0, 2])


def test_every_note_on_counts_for_the_raw_limit(monkeypatch):
    monkeypatch.setattr(config, "IMPORT_MAX_RAW_NOTES", 100)
    # 150 presses of one key with no note off: only 1 note stays (each press ends the one before).
    ev = [(i * 10, mido.Message("note_on", note=60, velocity=80, channel=0)) for i in range(150)]
    with pytest.raises(mi.MidiImportError, match="too many notes"):
        mi.parse(_midi([ev]), "x.mid")
    mi.parse(_midi([ev[:100]]), "x.mid")


def test_program_change_in_a_different_track():
    conductor = [(0, mido.MetaMessage("set_tempo", tempo=500000)),
                 (0, mido.Message("program_change", program=40, channel=1)),  # violin on channel 2
                 (0, mido.Message("program_change", program=0, channel=0))]
    own = [(0, mido.Message("program_change", program=24, channel=2))] + _scale(ch=2)  # its own: guitar
    parsed = mi.parse(_midi([conductor, _scale(ch=0), _scale(ch=1), own]), "c.mid")
    tracks = mi.track_list(parsed)
    assert [t["instrument"] for t in tracks] == ["Piano", "Strings", "Guitar"]
    assert [t["default"] for t in tracks] == [True, False, False]


def test_user_level_selects_the_fingering_mode():
    parsed = mi.parse((SYN / "one-track-vel0.mid").read_bytes(), "x.mid")  # white keys, Level 1
    easy = mi.build_song(parsed, user_level=1)
    hard = mi.build_song(parsed, user_level=4)
    assert set(easy["import"]["fingering"].values()) == {"beginner"}
    assert set(hard["import"]["fingering"].values()) == {"normal"}


def test_part_choice_errors():
    parsed = mi.parse((MIDI / "la-native.mid").read_bytes(), "x.mid")
    for parts in ([], [7], ["0"], [True]):
        with pytest.raises(mi.MidiImportError):
            mi.build_song(parsed, parts=parts)
    one = mi.build_song(parsed, parts=[1])
    assert len(one["notes"]) == 86


def test_swap_hands():
    parsed = mi.parse((MIDI / "la-native.mid").read_bytes(), "x.mid")
    a, b = mi.build_song(parsed), mi.build_song(parsed, swap=True)
    assert a["id"] != b["id"]
    ha = {(n["start"], n["pitch"]): n["hand"] for n in a["notes"]}
    assert all(ha[(n["start"], n["pitch"])] != n["hand"] for n in b["notes"])


def test_save_keeps_the_original_file_and_the_song_loads(data_dir):
    data = (MIDI / "la-native.mid").read_bytes()
    song = mi.import_file(data, "la-native.mid")
    folder = config.user_songs_path()
    assert (folder / f"{song['id']}.mid").read_bytes() == data
    saved = json.loads((folder / f"{song['id']}.json").read_text())
    assert saved["source"] == "midi" and saved["difficulty"]["skills"]
    loaded = songs.get(song["id"])
    assert loaded is not None and loaded["notes"] == song["notes"]
    summary = next(s for s in songs.list_summaries() if s["id"] == song["id"])
    assert summary["source"] == "midi" and "Level" in summary["difficulty"]["text"]
    # Built-in songs come first in the list.
    assert songs.list_summaries()[0]["source"] == "builtin"
