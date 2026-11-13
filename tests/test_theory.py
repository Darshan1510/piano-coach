import pytest

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
