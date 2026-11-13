import pytest

from riyaz import theory
from riyaz.theory import detect_chord, is_black, note_name


def test_note_names():
    assert note_name(60) == "C"
    assert note_name(60, octave=True) == "C4"
    assert note_name(61) == "C#"
    assert note_name(61, flats=True) == "Db"
    assert note_name(36, octave=True) == "C2"
    assert note_name(96, octave=True) == "C7"
    assert is_black(61) and not is_black(64)


@pytest.mark.parametrize("pitches,name,quality", [
    ([60, 64, 67], "C", "major"),
    ([57, 60, 64], "Am", "minor"),
    ([64, 67, 72], "C/E", "major"),
    ([67, 71, 74, 77], "G7", "major"),
    ([65, 69, 72, 76], "Fmaj7", "major"),
    ([62, 65, 69, 72], "Dm7", "minor"),
    ([59, 62, 65], "Bdim", None),
    ([60, 65, 67], "Csus4", None),
    ([58, 62, 65], "Bb", "major"),
    ([63, 66, 70], "Ebm", "minor"),
    ([48, 60, 64], "C", "major"),  # root + 3rd, no 5th
    ([60, 64, 67, 72, 76], "C", "major"),  # doubled notes
])
def test_detect_chord(pitches, name, quality):
    chord = detect_chord(pitches)
    assert chord is not None
    assert chord["name"] == name
    assert chord["quality"] == quality


def test_no_chord_for_few_keys():
    assert detect_chord([]) is None
    assert detect_chord([60, 64]) is None
    assert detect_chord([60, 72, 84]) is None  # one note name
    assert detect_chord([60, 61, 62]) is None  # cluster


def test_prefers_root_in_bass():
    # A C E G = Am7 (A in bass), C E G A = C6 (C in bass)
    assert detect_chord([57, 60, 64, 67])["name"] == "Am7"
    assert detect_chord([60, 64, 67, 69])["name"] == "C6"


# ---------------------------------------------------------------------------- Phase 3a
# music21 is a dev-only test oracle (DECISIONS.md): it is in the uv dev group, never in the app.

import itertools  # noqa: E402
import warnings  # noqa: E402
from pathlib import Path  # noqa: E402

MIDI = Path(__file__).resolve().parent / "data" / "midi"


def _m21():
    m = pytest.importorskip("music21")
    warnings.simplefilter("ignore")
    return m


def test_chord_names_match_music21():
    """Root and quality of the triads (all inversions) and 7th chords (root position), all 12 roots.

    The chords go to music21 with correct note names (intervals from the root), so that its root
    finder sees the right spelling. Not aug (symmetric: no single root). 7th chords in root
    position only: an inverted m7 is also a 6th chord (Eb G Bb C = Cm7/Eb = Eb6).
    """
    music21 = _m21()
    shapes = {"": ("M3", "P5"), "m": ("m3", "P5"), "dim": ("m3", "d5"), "7": ("M3", "P5", "m7"),
              "maj7": ("M3", "P5", "M7"), "m7": ("m3", "P5", "m7")}
    m21_quality = {"": "major", "m": "minor", "dim": "diminished"}
    checked = 0
    for root in range(12):
        for suffix, ivs in shapes.items():
            r = music21.pitch.Pitch(theory.chord_root_name(root).replace("b", "-") + "3")
            spelled = [r] + [r.transpose(i) for i in ivs]
            for inv in range(1 if len(ivs) == 3 else len(spelled)):
                ps = spelled[inv:] + [p.transpose("P8") for p in spelled[:inv]]
                midis = [p.midi for p in ps]
                ours = theory.detect_chord(midis)
                ch = music21.chord.Chord(ps)
                assert ours is not None, midis
                assert ch.root().pitchClass == root, (midis, ch.root())
                assert ours["root"] == theory.chord_root_name(root), (midis, ours)
                if suffix in m21_quality:
                    assert ch.quality == m21_quality[suffix], (midis, ch.quality)
                    assert ours["name"].split("/")[0] == theory.chord_root_name(root) + suffix
                else:
                    assert ch.seventh is not None and ours["name"].split("/")[0].endswith(suffix)
                checked += 1
    assert checked == 12 * (3 * 3 + 3)


def test_key_detection_matches_music21_krumhansl():
    """Our Krumhansl-Schmuckler key = music21 'key.krumhanslkessler' on all test files."""
    music21 = _m21()
    from riyaz.importers import midi_import as mi

    # Not empty-tracks.mid: its notes with no note off get other lengths in music21.
    files = sorted(MIDI.glob("*.mid")) + sorted((MIDI / "synthetic").glob("*.mid"))
    for path in [f for f in files if f.name != "empty-tracks.mid"]:
        song = mi.build_song(mi.parse(path.read_bytes(), path.name))
        k = music21.converter.parse(str(path)).analyze("key.krumhanslkessler")
        ours = theory.key_candidates(song["notes"])[0]
        assert theory.key_name(ours[1], ours[2]).lower() == f"{k.tonic.name.replace('-', 'b')} {k.mode}".lower(), path.name


def test_song_key_uses_the_key_signature_for_a_near_tie():
    """Les Graces: the notes say D major (0.856) or G major (0.822); the file says G (music21 agrees)."""
    music21 = _m21()
    from riyaz.importers import midi_import as mi

    for name in ("les-graces.mid", "la-native.mid", "bach-minuet-a-minor-bwv-anh-120.mid"):
        song = mi.build_song(mi.parse((MIDI / name).read_bytes(), name))
        k = music21.converter.parse(str(MIDI / name)).analyze("key")
        assert song["key"].lower() == f"{k.tonic.name} {k.mode}".lower(), name


def test_detect_key_simple():
    c = [{"pitch": p, "dur": 1.0} for p in (60, 62, 64, 65, 67, 69, 71, 72, 67, 64, 60)]
    assert theory.detect_key(c) == "C major"
    a = [{"pitch": p, "dur": 1.0} for p in (57, 59, 60, 62, 64, 65, 68, 69, 64, 57, 57, 60)]
    assert theory.detect_key(a) == "A minor"
    assert theory.detect_key([]) == ""


def test_chords_for_notes_per_bar_and_half_bar():
    def block(pcs, start, dur=4.0):
        return [{"pitch": 48 + p, "start": start, "dur": dur} for p in pcs]

    notes = block((0, 4, 7), 0) + block((5, 9, 12), 4) + block((7, 11, 14), 8, 2) + block((0, 4, 7), 10, 2)
    assert [(c["name"], c["start"], c["dur"]) for c in theory.chords_for_notes(notes, 4.0, 12.0)] == [
        ("C", 0.0, 4.0), ("F", 4.0, 4.0), ("G", 8.0, 2.0), ("C", 10.0, 2.0)]
    # Same chord in 2 bars: one entry. An empty bar: no entry.
    notes = block((0, 4, 7), 0) + block((0, 4, 7), 4) + block((9, 12, 16), 12)
    assert [(c["name"], c["start"], c["dur"]) for c in theory.chords_for_notes(notes, 4.0, 16.0)] == [
        ("C", 0.0, 8.0), ("Am", 12.0, 4.0)]


def test_chord_names_of_imported_songs_match_music21_roots():
    """Per-bar chord roots of a 2-hand file vs music21 chordify (root of the bar's notes)."""
    music21 = _m21()
    from riyaz.importers import midi_import as mi

    path = MIDI / "synthetic" / "chords-one-track.mid"
    song = mi.build_song(mi.parse(path.read_bytes(), path.name))
    score = music21.converter.parse(str(path)).chordify()
    roots = []
    for m in score.recurse().getElementsByClass("Measure"):
        pcs = [p.midi for c in m.notes for p in c.pitches]
        roots.append(music21.chord.Chord([p for p in pcs if p < 60]).root().name)
    ours = [c["name"] for c in song["chords"]]
    assert [r.replace("-", "b") for r in roots[1:4]] == ours[1:4]


def test_pairwise_chord_detect_no_crash():
    for ps in itertools.combinations(range(48, 62), 3):
        theory.detect_chord(ps)
