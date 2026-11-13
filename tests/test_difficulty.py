"""Difficulty check and song card text (PLAN 8.4)."""

from pathlib import Path

from riyaz import difficulty
from riyaz.importers import midi_import as mi

MIDI = Path(__file__).resolve().parent / "data" / "midi"


def song(name):
    path = MIDI / name
    return mi.build_song(mi.parse(path.read_bytes(), path.name))


def test_beginner_tune_is_playable_at_its_level():
    s = song("synthetic/drums.mid")  # right hand, C position, white keys
    assert s["difficulty"]["skills"] == ["right_hand"] and s["level"] == 1
    assert difficulty.card_text(s["difficulty"], 1) == {
        "playable": True, "needs": [], "level": None, "text": "You can play this song now."}


def test_two_hands_need_level_3():
    s = song("synthetic/one-track-vel0.mid")
    assert s["level"] == 3
    c = difficulty.card_text(s["difficulty"], 1)
    assert c["text"] == "This song needs: the left hand, both hands together. You learn these in Level 3."
    assert difficulty.card_text(s["difficulty"], 3)["playable"]


def test_public_domain_pieces_measures():
    s = song("les-graces.mid")
    st = s["difficulty"]["stats"]
    assert st["black_keys"] > 0 and st["keys_together"] > 0 and st["both_hands_notes"] > 0
    assert {"black_keys", "keys_together", "both_hands", "hand_moves"} <= set(s["difficulty"]["skills"])
    c = difficulty.card_text(s["difficulty"], 1)
    assert not c["playable"] and c["text"].startswith("This song needs: ")
    assert c["text"].endswith(f"You learn these in Level {c['level']}.") and c["level"] == s["level"]
    assert "more skills" in c["text"]  # the card names at most 4 skills


def test_fast_runs_and_notes_per_second():
    notes = [{"pitch": 60 + (i % 5) * 2 - (1 if (i % 5) * 2 in (6,) else 0), "start": i * 0.25, "dur": 0.25,
              "hand": "R", "finger": None} for i in range(16)]
    s = {"bpm": 120, "notes": notes, "hand_positions": []}
    d = difficulty.analyze(s)
    assert d["stats"]["notes_per_second"] == 8.0 and "fast_runs" in d["skills"] and d["level"] == 7


def test_card_text_has_no_locked_words():
    import re

    locked = re.compile(r"\b(sharp|flat|major|minor|scale|interval|progression|bar|measure|beat|tempo|chord|rest)s?\b", re.I)
    for _lvl, name in difficulty.SKILLS.values():
        assert not locked.search(name), name
    all_skills = {"skills": list(difficulty.SKILLS)}
    for level in range(1, 11):
        assert not locked.search(difficulty.card_text(all_skills, level)["text"])
