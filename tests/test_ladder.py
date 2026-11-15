"""Phase 5b: course Levels 4-8 (PLAN 8.3): the 13 new songs, their skill moments and term unlocks
(PLAN 7.4, 8.2), level progression 3 -> 8, and the left-hand patterns of the simplifier (8.4).
Fake clock, no CoreMIDI (the real-port runs are in PROGRESS.md and tests/test_midi_virtual.py)."""

import pytest
from fastapi.testclient import TestClient

from riyaz import config, course, patterns, songs, theory
from riyaz.practice import Practice
from riyaz.server import create_app
from riyaz.songs import position_keys
from tests.test_play import of, simulate

NEW = {
    "jingle-bells": 4, "when-the-saints": 4, "yankee-doodle": 4,
    "happy-birthday": 5, "amazing-grace": 5, "clementine": 5,
    "canon-in-d": 6, "pop-loop": 6,
    "minuet-in-g": 7, "ode-to-joy-full": 7,
    "scarborough-fair": 8, "greensleeves": 8, "aura-lee": 8, "vande-mataram": 8,
}
OWN = {"Origin": "http://127.0.0.1:8020"}


def song(sid):
    return songs.get(sid)


def ladder_hands(sid):
    """The hands of the ladder entry. Vande Mataram is a Level 8 song that may not be in
    data/course/ladder.json yet: then both hands."""
    entry = course.ladder_entry(sid)
    return entry["hands"] if entry else ["R", "L"]


def line(s, hand="R"):
    """One key at a time (the highest key of keys together), in time order."""
    out, last = [], None
    for n in sorted((n for n in s["notes"] if n["hand"] == hand), key=lambda n: (n["start"], -n["pitch"])):
        if last is not None and abs(n["start"] - last) < 1e-6:
            continue
        out.append(n)
        last = n["start"]
    return out


# ---------------------------------------------------------------------- the songs


def test_the_generated_files_are_up_to_date():
    from tools import make_ladder_songs

    for spec in make_ladder_songs.SONGS:
        path = make_ladder_songs.SONG_DIR / f"{spec['id']}.json"
        assert path.read_text(encoding="utf-8") == make_ladder_songs.dump(make_ladder_songs.build(spec)), spec["id"]
    assert {s["id"] for s in make_ladder_songs.SONGS} == set(NEW)


@pytest.mark.parametrize("sid", sorted(NEW))
def test_song_shape_and_fingering(sid):
    s = song(sid)
    assert s["level"] == NEW[sid] and s["source"] == "builtin" and "public domain" in s["credit"]
    entry = course.ladder_entry(sid)
    assert (entry is None and sid == "vande-mataram") or entry["level"] == NEW[sid]
    for n in s["notes"]:
        pos = [p for p in s["hand_positions"] if p["hand"] == n["hand"] and p["start"] <= n["start"] + 1e-9][-1]
        assert position_keys(pos)[n["finger"] - 1] == n["pitch"], (sid, n)
        assert config.KEY_LOW <= n["pitch"] <= config.KEY_HIGH
    # No key twice at one time; the right hand stays above the left hand.
    seen = {}
    for n in sorted(s["notes"], key=lambda n: n["start"]):
        prev = seen.get(n["pitch"])
        assert prev is None or prev["start"] + prev["dur"] <= n["start"] + 1e-9, (sid, prev, n)
        seen[n["pitch"]] = n
    left = [n["pitch"] for n in s["notes"] if n["hand"] == "L"]
    assert not left or max(left) < 60, sid  # the left hand stays below middle C
    # Keys together only from Level 5 (PLAN 8.3); black keys only from Level 4.
    starts = [n["start"] for n in s["notes"] if n["hand"] == "L"]
    single_left = ("minuet-in-g", "scarborough-fair")  # one key at a time (scarborough: broken chords)
    assert (len(starts) != len(set(starts))) == (NEW[sid] >= 5 and sid not in single_left), sid
    # Parts cover the song with plain names; the song ends at the end of a group of clicks.
    secs = s["sections"]
    assert secs[0]["start"] == 0 and secs[-1]["end"] == s["end"] and all(a["end"] == b["start"] for a, b in zip(secs, secs[1:]))
    assert [x["name"] for x in secs] == [f"Part {i + 1}" for i in range(len(secs))]
    assert s["end"] % s["time_signature"][0] == 0


def test_black_keys_from_level_4_and_sharp_names_unlock_there():
    for sid, lv in NEW.items():
        if sid in ("jingle-bells", "when-the-saints", "yankee-doodle"):
            assert any(theory.is_black(n["pitch"]) for n in song(sid)["notes"] if n["hand"] == "R"), sid
    for sid in ("mary-had-a-little-lamb", "ode-to-joy", "frere-jacques-both-hands"):
        assert not any(theory.is_black(n["pitch"]) for n in song(sid)["notes"])
    terms = course.content()["terms_by_id"]
    skills = course.content()["skills"]
    for tid, t in terms.items():
        by = t["unlocked_by"]
        level = skills[by["skill"]]["level"] if "skill" in by else 1
        assert level == t["level"], (tid, level, t["level"])  # PLAN 7.4: the unlock level of each term
    assert terms["sharp_flat"]["unlocked_by"] == {"skill": "black_names"}
    assert terms["chord"]["unlocked_by"] == {"skill": "chord_keys"}
    assert terms["major_minor"]["unlocked_by"] == {"skill": "happy_sad"}
    assert terms["progression"]["unlocked_by"] == {"skill": "chord_pattern"}
    assert terms["scale"]["unlocked_by"] == {"skill": "scale"}


# The well-known start of each tune (C4 = 60): keys and counts. Checked by hand against the
# published public-domain tunes (DECISIONS.md "Phase 5b"); a change here needs a new check.
# This data is typed here from the sources, not taken from tools/make_ladder_songs.py.
# Sources (moved to the key of the song):
#   amazing-grace: https://hymnary.org/tune/new_britain (incipit 51313 21655 13132)
#   clementine: https://www.flutetunes.com/tunes/oh-my-darling-clementine.mid (in G)
#   aura-lee: https://www.flutetunes.com/tunes/aura-lee.mid (in G)
#   vande-mataram: Swarabitan vol. 46, https://archive.org/details/in.ernet.dli.2015.356988 (= the typed copy
#   https://www.geetabitan.com/lyrics/rs-b/bande-mataram-bengali-notation.html), Sa = C4, grace notes left out
START = {
    "jingle-bells": ([69, 69, 69, 69, 69, 69, 69, 72, 65, 67, 69], [1, 1, 2, 1, 1, 2, 1, 1, 1.5, 0.5, 4]),  # in F
    "when-the-saints": ([65, 69, 70, 72, 65, 69, 70, 72], [1, 1, 1, 4, 1, 1, 1, 4], [1, 2, 3, 4, 9, 10, 11, 12]),  # in F, a pause of 1 count before "Oh"
    "yankee-doodle": ([65, 65, 67, 69, 65, 69, 67, 60, 65, 65, 67, 69, 65, 64], [1] * 12 + [2, 2]),  # in F
    "happy-birthday": ([67, 67, 69, 67, 72, 71, 67, 67, 69, 67, 74, 72], [0.75, 0.25, 1, 1, 1, 2, 0.75, 0.25, 1, 1, 1, 2]),
    "amazing-grace": ([67, 72, 76, 72, 76, 74, 72, 69, 67], [1, 2, 0.5, 0.5, 2, 1, 2, 1, 2]),
    "clementine": ([72, 72, 72, 67, 76, 76, 76, 72, 72, 76, 79, 79, 77, 76, 74], [0.75, 0.25, 1, 1, 0.75, 0.25, 1, 1, 0.5, 0.5, 1, 1, 0.5, 0.5, 2]),
    "canon-in-d": ([78, 76, 74, 73, 71, 69, 71, 73], [2] * 8),
    "minuet-in-g": ([74, 67, 69, 71, 72, 74, 67, 67, 76, 72, 74, 76, 78, 79, 67, 67], [1, .5, .5, .5, .5, 1, 1, 1, 1, .5, .5, .5, .5, 1, 1, 1]),
    "scarborough-fair": ([62, 62, 69, 69, 64, 65, 64, 62], [2, 1, 2, 1, 1.5, 0.5, 1, 3]),
    "greensleeves": ([69, 72, 74, 76, 77, 76, 74, 71, 67, 69, 71, 72, 69, 69, 68, 69], [1, 2, 1, 1.5, .5, 1, 2, 1, 1.5, .5, 1, 2, 1, 1.5, .5, 1]),
    "aura-lee": ([67, 72, 71, 72, 74, 69, 74, 72, 71, 69, 71, 72], [1, 1, 1, 1, 1, 1, 2, 1, 1, 1, 1, 4]),
    "vande-mataram": ([72, 72, 71, 72, 74, 72, 70, 69, 67, 67, 69, 67, 65, 67, 65, 64],
                      [2, 4, .5, .5, .5, .5, .5, .5, 3, 1, .5, .5, .5, .5, .5, .5]),
}

# Passages that a review changed (Phase 5b fixes): (start beat, [(key, counts), ...]) of the tune,
# typed from the source of each one (moved to the key of the song).
PASSAGES = {
    # Reviewer's note (no source file): "... that number" bars 12-13: C, B flat (4 counts), B flat, A, B flat.
    "when-the-saints": [(44, [(72, 1), (70, 4), (70, 1), (69, 1), (70, 1), (72, 2)])],
    # Excell (1900), Wikipedia "Amazing Grace" LilyPond score (in G): "me" G 2 + "I" E 1, then the second half.
    "amazing-grace": [(21, [(79, 2), (76, 1), (79, 1.5), (76, .5), (79, .5), (76, .5), (72, 2), (67, 1),
                            (69, 1.5), (72, .5), (72, .5), (69, .5), (67, 2), (67, 1),
                            (72, 2), (76, .5), (72, .5), (76, 2), (74, 1), (72, 3)])],
    # flutetunes MIDI: dotted pairs after bar 3.
    "clementine": [(12, [(74, 2), (74, .75), (76, .25), (77, 1), (77, 1), (76, .75), (74, .25),
                         (76, 1), (72, 1), (72, .75), (76, .25), (74, 1), (67, 1), (71, .75), (74, .25), (72, 3)])],
    # Reviewer's note: line 3 starts with a pickup D ("A 2 + D 1" in place of "A 3").
    "scarborough-fair": [(21, [(69, 2), (74, 1), (74, 2), (74, 1), (72, 2), (69, 1)])],
    # flutetunes MIDI: the refrain (lines 3 and 4) after the verse line 2 times.
    "aura-lee": [(32, [(76, 1.5), (76, .5), (76, 2), (76, 1.5), (76, .5), (76, 2), (76, 1), (74, 1), (72, 1), (74, 1),
                       (76, 4), (76, 1), (76, 1), (77, 1), (76, 1), (74, 1), (69, 1), (74, 1.5), (72, .5),
                       (72, 1), (71, 1), (76, 1.5), (74, .5), (72, 4)])],
    # Swarabitan: line 2 ("-ram, ma-") and line 6 ("su-pha-lan, ma-la-ya-ja shi-").
    "vande-mataram": [(16, [(62, 8), (65, 1), (62, 1), (65, 2), (64, .5), (65, .5), (67, 1), (65, .5), (67, .5), (69, 1)]),
                      (80, [(62, 1), (64, 1), (62, .5), (60, .5), (59, 1), (60, 4),
                            (62, 1), (62, 1), (65, 1), (65, 1), (67, 3), (65, 1)])],
}


@pytest.mark.parametrize("sid", sorted(PASSAGES))
def test_checked_passages(sid):
    notes = line(song(sid))
    for beat, want in PASSAGES[sid]:
        i = next(k for k, n in enumerate(notes) if n["start"] == pytest.approx(beat))
        got = notes[i:i + len(want)]
        assert [(n["pitch"], n["dur"]) for n in got] == want, (sid, beat)
        t = beat
        for n, (_, d) in zip(got, want):  # no gap in the passage
            assert n["start"] == pytest.approx(t), (sid, n)
            t += d


def test_yankee_doodle_hand_move_on_the_repeated_f():
    """From beat 16: F F G A B flat A G F with fingers 1 1 2 3 4 3 2 1 (the hand moves to F on beat 16)."""
    s = song("yankee-doodle")
    notes = line(s)
    i = next(k for k, n in enumerate(notes) if n["start"] == 16)
    assert [(n["pitch"], n["finger"]) for n in notes[i:i + 8]] == [(65, 1), (65, 1), (67, 2), (69, 3), (70, 4), (69, 3), (67, 2), (65, 1)]
    assert any(p["hand"] == "R" and p["start"] == 16 and p["thumb_pitch"] == 65 for p in s["hand_positions"])


@pytest.mark.parametrize("sid", sorted(START))
def test_melodies_start_correctly(sid):
    keys, counts, *starts = START[sid]
    notes = line(song(sid))
    assert [n["pitch"] for n in notes[: len(keys)]] == keys, sid
    assert [n["dur"] for n in notes[: len(counts)]] == counts, sid
    if starts:
        assert [n["start"] for n in notes[: len(starts[0])]] == starts[0], sid
        return
    t = notes[0]["start"]
    for n, d in zip(notes, counts):  # the notes follow each other (no gap) in the first phrase
        assert n["start"] == pytest.approx(t), (sid, n)
        t += d


def test_ode_to_joy_full_has_the_level_1_tune_and_the_8_key_walk():
    full = line(song("ode-to-joy-full"))
    walk = [n["pitch"] for n in full[:8]]
    assert walk == [60, 62, 64, 65, 67, 69, 71, 72] and [n["finger"] for n in full[:8]] == [1, 2, 3, 1, 2, 3, 4, 5]
    l1 = line(song("ode-to-joy"))
    assert [(n["pitch"], n["start"] + 8, n["dur"]) for n in l1] == [(n["pitch"], n["start"], n["dur"]) for n in full[8:8 + len(l1)]]
    # The B part (D D E C ...) and the last A part: the whole tune (16 groups of 4 clicks after the walk).
    b = [n["pitch"] for n in full[8 + len(l1):]]
    assert b[:17] == [62, 62, 64, 60, 62, 64, 65, 64, 60, 62, 64, 65, 64, 62, 60, 62, 55]
    assert b[17:] == [n["pitch"] for n in l1[15:]]
    assert song("ode-to-joy-full")["end"] == 8 + 64


CHORDS = {  # the left-hand keys together, in order (roots), as written in tools/make_ladder_songs.py
    "canon-in-d": ["D", "A", "Bm", "F#m", "G", "D", "G", "A"] * 2 + ["D"],
    "pop-loop": ["C", "G", "Am", "F"] * 2 + ["G", "D", "Em", "C"] * 2,
    "happy-birthday": ["C", "G", "G", "C", "C", "F", "C", "G", "C"],
    "clementine": ["C", "C", "C", "G", "G", "C", "G", "C"],
}


def _music21_chords(s):
    from music21 import chord, harmony  # noqa: F401  (dev-only oracle, DECISIONS "Phase 3a")

    groups = {}
    for n in s["notes"]:
        if n["hand"] == "L":
            groups.setdefault(n["start"], []).append(n["pitch"])
    out = []
    for t in sorted(groups):
        if len(groups[t]) >= 3:
            c = chord.Chord(groups[t])
            root = c.root().name.replace("-", "b")
            out.append((t, root + ("m" if c.quality == "minor" else ""), c.quality))
    return out


@pytest.mark.parametrize("sid", sorted(CHORDS))
def test_left_hand_chords_are_the_written_chords_music21(sid):
    pytest.importorskip("music21")
    got = [name for _, name, _ in _music21_chords(song(sid))]
    assert got == CHORDS[sid], sid


@pytest.mark.parametrize("sid", [s for s, lv in NEW.items() if lv >= 5 and s not in ("minuet-in-g", "vande-mataram")])
def test_left_hand_fits_the_tune_music21(sid):
    """music21 oracle: each left-hand chord (keys together, or a broken chord / pattern of one
    group of clicks) is a major or minor triad, and the tune key at the start of each group of
    clicks is a key of that chord in most groups (60% or more: a key just before the chord key,
    like "A" in "Happy BIRTH-day" over C, is normal in these tunes)."""
    pytest.importorskip("music21")
    from music21 import chord

    s = song(sid)
    bar = float(s["time_signature"][0])
    left = [n for n in s["notes"] if n["hand"] == "L"]
    if not left:
        pytest.skip("no left hand")
    fits = total = 0
    b = 0.0
    while b < s["end"] - 1e-6:
        lh = [n["pitch"] for n in left if b - 1e-6 <= n["start"] < b + bar - 1e-6]
        if sid == "greensleeves" and b < 6:
            b += bar
            continue  # the pickup group: no left hand
        if len(set(p % 12 for p in lh)) >= 3:
            half = [n["pitch"] for n in left if b - 1e-6 <= n["start"] < b + bar / 2 - 1e-6] if sid == "greensleeves" else lh
            c = chord.Chord(half if len(set(p % 12 for p in half)) >= 3 else lh)
            assert c.quality in ("major", "minor"), (sid, b, c.pitchedCommonName)
            down = [n for n in s["notes"] if n["hand"] == "R" and n["start"] <= b + 1e-6 < n["start"] + n["dur"]]
            if down:
                total += 1
                fits += max(n["pitch"] for n in down) % 12 in {p.pitchClass for p in c.pitches}
        b += bar
    assert total >= 6 and fits / total >= 0.6, (sid, fits, total)


@pytest.mark.parametrize("sid", sorted(NEW))
def test_key_of_the_tune_music21(sid):
    """music21 key analysis (Krumhansl-Kessler) of the tune (right hand) gives the key family of the
    song: the same key signature (a minor key and its major key share it). Scarborough Fair (Dorian,
    no flat), Greensleeves (minor with G and G sharp) and the pop loop (C, then G) may be 1 away."""
    pytest.importorskip("music21")
    from music21 import key, note, stream

    s = song(sid)
    st = stream.Stream()
    for n in s["notes"]:
        if n["hand"] != "R":
            continue
        x = note.Note(n["pitch"])
        x.quarterLength = n["dur"]
        st.insert(n["start"], x)
    got = st.analyze("key")
    tonic, mode = s["key"].split()
    want = key.Key(tonic.replace("b", "-"), mode)
    near = 1 if sid in ("scarborough-fair", "greensleeves", "pop-loop") else 0
    assert abs(got.sharps - want.sharps) <= near, (sid, str(got), got.sharps, want.sharps)


# ---------------------------------------------------------------------- fake player, fake clock


class Clock:
    def __init__(self):
        self.t = 50.0

    def __call__(self):
        return self.t


@pytest.mark.parametrize("sid", sorted(NEW))
def test_new_song_completes_in_wait_mode(sid):
    clk = Clock()
    events = []
    p = Practice(events.append, now=clk, threaded=False)
    s = song(sid)
    hands = ladder_hands(sid)
    p.start(s, mode="wait", hands=hands, count_in=True, speed=1.5)
    for _ in range(200000):
        clk.t += 0.01
        p.tick()
        st = p.state()
        if st["done"]:
            break
        if st["waiting"]:
            for e in st["expected"]:
                p.on_midi({"type": "note_on", "pitch": e["pitch"], "velocity": 80, "t": clk.t})
            clk.t += 0.01
            for e in st["expected"]:
                p.on_midi({"type": "note_off", "pitch": e["pitch"], "t": clk.t})
    end = of(events, "practice_end")
    assert end and end[0]["completed"] and end[0]["wrong"] == 0 and end[0]["accuracy"] == 100.0
    assert end[0]["stops"] == len({n["start"] for n in s["notes"] if n["hand"] in hands})


@pytest.mark.parametrize("sid", sorted(NEW))
def test_new_song_exact_play_along_scores_at_least_98(sid):
    hands = ladder_hands(sid)
    for hs in ({"R"}, set(hands)):
        p, events, _ = simulate(song(sid), sorted(hs, key="RL".index))
        end = of(events, "practice_end")[0]
        assert end["score"]["total"] >= 98 and end["score"]["missed"] == 0, (sid, hs, end["score"])


# ---------------------------------------------------------------------- course: levels 3 -> 8


@pytest.fixture
def client(data_dir):
    app = create_app(start_midi=False)
    with TestClient(app, base_url="http://127.0.0.1:8020") as c:
        c.riyaz = app.state.riyaz
        c.hub = app.state.hub
        yield c


def _play(c, sid, hands, score=100.0):
    published = []
    orig = c.hub.publish
    c.hub.publish = lambda e: (published.append(e), orig(e))
    try:
        c.riyaz["practice"].sink({"type": "practice_end", "song_id": sid, "mode": "play", "hands": hands, "speed": 1.0,
                                  "section": None, "completed": True, "accuracy": score, "stops": 10, "wrong": 0,
                                  "errors": [], "score": {"total": score, "accuracy": score, "timing": 100, "length": 100,
                                                          "stars": 3, "hit": 10, "missed": 0, "perfect": 10}})
        c.riyaz["flush_results"]()
    finally:
        c.hub.publish = orig
    return [e for e in published if e.get("type") == "course"][-1]


def test_level_3_to_8_and_all_done(client):
    c = client
    for e in course.ladder_entries():
        if e["level"] <= 3:
            _play(c, e["song_id"], e["hands"])
    st = c.get("/api/course").json()
    assert st["level"] == 4 and st["max_level"] == 8 and st["current_song"] == "jingle-bells"
    for lv in range(4, 9):
        entries = [e for e in course.ladder_entries() if e["level"] == lv]
        assert c.get("/api/course").json()["level"] == lv
        r = _play(c, entries[0]["song_id"], ["R"]) if entries[0]["hands"] != ["R"] else None
        if r is not None:
            assert not r["done"]  # one hand only: not done (the ladder hands are both hands)
        for e in entries:
            r = _play(c, e["song_id"], e["hands"])
        assert r["level_up"] and r["level"] == lv + 1, (lv, r)
        st = c.get("/api/course").json()
        assert st["levels"][lv - 1]["done"] and st["bar_lines"]
    st = c.get("/api/course").json()
    assert st["all_done"] and st["level"] == 9 and st["user_level"] == 8
    assert c.get("/api/songs").json()["user_level"] == 8


def test_terms_unlock_at_their_levels_through_the_skill_moments(client):
    c = client
    store = c.riyaz["store"]
    c.post("/api/course/skip", json={"level": 8}, headers=OWN)
    order = []
    for e in course.ladder_entries():
        for sk in e["skills"]:
            have = set(store.terms())
            r = c.riyaz["course"].complete_skill(sk["id"])
            for t in r["unlocked"]:
                order.append((t, e["level"]))
            assert set(store.terms()) - have == set(r["unlocked"])
    levels = dict(order)
    assert levels["sharp_flat"] == 4 and levels["chord"] == 5 and levels["major_minor"] == 5
    assert levels["progression"] == 6 and levels["scale"] == 7
    # Words page: after the unlock the card is there, with the term.
    t = {x["id"]: x for x in c.get("/api/course/terms").json()["terms"]}
    assert t["sharp_flat"]["unlocked"] and t["sharp_flat"]["term"] == "sharp"


def test_sharp_and_flat_names_only_after_the_level_4_moment(client):
    """The black-key moment (Jingle Bells) comes before the names (When the Saints): it uses the
    plain words. The keyboard flag WORDS.sharpFlat follows the "sharp_flat" unlock (terms.js)."""
    c = client
    c.post("/api/course/skip", json={"level": 4}, headers=OWN)
    sk = c.get("/api/course/skills/hand_move").json()
    assert "black key" in " ".join(sk["text"]) and "flat" not in " ".join(sk["text"]).lower()
    t = {x["id"]: x for x in c.get("/api/course/terms").json()["terms"]}
    assert not t["sharp_flat"]["unlocked"] and "term" not in t["sharp_flat"]
    c.riyaz["course"].complete_skill("black_names")
    sk = c.get("/api/course/skills/hand_move").json()
    assert "[[sharp_flat|B flat]]" in " ".join(sk["text"])
    js = c.get("/static/js/terms.js").text
    assert 'WORDS.sharpFlat = this.unlocked("sharp_flat")' in js


def test_skipped_level_5_moment_gives_plain_words_at_level_6(client):
    """A user who skipped to Level 6: "chord" is locked, so the Level 6 texts say "groups of keys"."""
    c = client
    c.post("/api/course/skip", json={"level": 6}, headers=OWN)
    sk = c.get("/api/course/skills/four_chords").json()
    text = " ".join([sk["name"]] + sk["text"])
    assert "groups of keys" in text and "chord" not in text.replace("[[", "").lower().replace("chord pattern", "")
    assert "A with a sad sound" in text  # major/minor locked too
    lv6 = next(lv for lv in c.get("/api/course").json()["levels"] if lv["level"] == 6)
    assert "chord" not in (lv6["title"] + lv6["text"]).lower()


# ---------------------------------------------------------------------- simplifier patterns (Level 6 and 8)


def _block(start, dur, keys):
    return [{"pitch": p, "start": start, "dur": dur, "hand": "L", "vel": 60} for p in keys]


def test_left_hand_patterns_for_levels_6_and_8():
    lh = _block(0, 4, [48, 52, 55]) + _block(4, 4, [43, 47, 50])
    assert patterns.apply(lh, 5, 4) == lh  # Level 5: block chords
    loop = patterns.apply(lh, 6, 4)  # Level 6: the chord again on click 3 (the loop template)
    assert sorted({n["start"] for n in loop}) == [0, 2, 4, 6] and all(n["dur"] == 2 for n in loop)
    k = patterns.apply(lh, 8, 4)  # Level 8, 4 clicks: keherwa
    first = sorted((n["start"], n["pitch"]) for n in k if n["start"] < 4)
    assert first == [(0, 48), (1.5, 52), (1.5, 55), (2, 48), (3, 52), (3, 55)]
    d = patterns.apply(_block(0, 6, [45, 48, 52]), 8, 6)  # 6 clicks: dadra
    assert sorted((n["start"], n["pitch"]) for n in d) == [(0, 45), (1, 48), (1, 52), (3, 45), (4, 48), (4, 52)]
    assert patterns.apply(_block(0, 3, [45, 48, 52]), 8, 3)[0]["dur"] == 1  # 3 clicks: half of dadra
    assert patterns.apply(_block(0, 5, [45, 48, 52]), 8, 5) == _block(0, 5, [45, 48, 52])  # 5 clicks: no pattern


def test_level_8_easy_version_of_an_imported_song_has_a_rhythm_feel(data_dir):
    from pathlib import Path

    from riyaz import simplify
    from riyaz.importers import midi_import as mi

    path = Path(__file__).resolve().parent / "data" / "midi" / "la-native.mid"
    src = mi.build_song(mi.parse(path.read_bytes(), path.name))
    v6 = simplify.make_version(src, left="chords", key="auto", level=6)
    v8 = simplify.make_version(src, left="chords", key="auto", level=8)
    num = src["time_signature"][0]
    l6 = {n["start"] for n in v6["notes"] if n["hand"] == "L"}
    l8 = [n for n in v8["notes"] if n["hand"] == "L"]
    assert len({n["start"] for n in l8}) > len(l6) or num not in (3, 4, 6)
    if num == 4:
        assert any(abs(n["start"] % 4 - 1.5) < 1e-6 for n in l8)  # the keherwa lift just after click 2
