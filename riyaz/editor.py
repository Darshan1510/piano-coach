"""Song editor: check and save an edited song (PLAN 11.4).

The page (static/js/editor.js) changes a copy of the song (notes, hands, fingers, parts, the
loop, the speed, the key) and sends the whole song. This module checks it, gives fingers to new
notes (the automatic fingering), makes the hand positions again from the fingers, and runs the
difficulty check. Built-in songs are read-only: "Save as my copy" makes a new user song.

All error texts are for the user (ASD-STE100, PLAN 7.4 words).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re

from . import config, difficulty, fingering, songs, theory
from .handsplit import onsets

EPS = 1e-6
KEY_NAMES = tuple(theory.key_name(pc, mode) for mode in ("major", "minor") for pc in range(12))


class EditorError(ValueError):
    """The text is for the user."""


def _number(v, text: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        raise EditorError(text)
    return float(v)


def check(raw: dict) -> dict:
    """Check the edited song. Returns a clean song dict (not validated by songs.validate yet)."""
    if not isinstance(raw, dict):
        raise EditorError("The app did not get the song. Try again.")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise EditorError("Give the song a name.")
    bpm = _number(raw.get("bpm"), "Set a speed from 20 to 300.")
    if not 20 <= bpm <= 300:
        raise EditorError("Set a speed from 20 to 300.")
    key = raw.get("key") or ""
    if key and key not in KEY_NAMES:
        raise EditorError("Select a key for the song from the list.")
    notes_in = raw.get("notes")
    if not isinstance(notes_in, list) or not notes_in:
        raise EditorError("The song has no notes. Add one or more notes.")
    if len(notes_in) > config.EDITOR_MAX_NOTES:
        raise EditorError(f"The song has too many notes. The limit is {config.EDITOR_MAX_NOTES}.")
    notes = []
    for n in notes_in:
        if not isinstance(n, dict):
            raise EditorError("The app did not get the song. Try again.")
        pitch = n.get("pitch")
        if not isinstance(pitch, int) or isinstance(pitch, bool) or not config.KEY_LOW <= pitch <= config.KEY_HIGH:
            raise EditorError("A note is not on the 61 keys of the keyboard. Move the note up or down.")
        start = _number(n.get("start"), "A note has no start time. Move the note.")
        dur = _number(n.get("dur"), "A note has no length. Change the length of the note.")
        if start < 0:
            raise EditorError("A note starts before the start of the song. Move the note to the right.")
        if dur < 0.05:
            raise EditorError("A note is too short. Make the note longer.")
        hand = n.get("hand")
        if hand not in ("R", "L"):
            raise EditorError("A note has no hand. Select the right hand or the left hand for the note.")
        finger = n.get("finger")
        if finger is not None and (not isinstance(finger, int) or isinstance(finger, bool) or not 1 <= finger <= 5):
            raise EditorError("A finger number must be 1 to 5.")
        vel = n.get("vel", 80)
        vel = int(vel) if isinstance(vel, (int, float)) and not isinstance(vel, bool) else 80
        notes.append({"pitch": pitch, "start": round(start, 4), "dur": round(dur, 4), "hand": hand,
                      "finger": finger, "vel": max(1, min(127, vel))})
    seen = set()
    for n in notes:
        k = (n["start"], n["pitch"])
        if k in seen:
            raise EditorError("Two notes on the same key start at the same time. Remove one of them.")
        seen.add(k)
    # The same key cannot sound 2 times at once (also in 2 hands): the note before ends when
    # the next note on that key starts.
    by_key: dict[int, list[dict]] = {}
    for n in notes:
        by_key.setdefault(n["pitch"], []).append(n)
    for lst in by_key.values():
        lst.sort(key=lambda n: n["start"])
        for a, b in zip(lst, lst[1:]):
            if b["start"] < a["start"] + a["dur"] - EPS:
                room = round(b["start"] - a["start"], 4)
                if room < 0.05:
                    raise EditorError("Two notes on the same key sound at the same time. Move one of them.")
                a["dur"] = room
    for hand in ("R", "L"):
        for g in onsets([n for n in notes if n["hand"] == hand]):
            if len(g) > 5:
                raise EditorError("One hand has more than 5 keys at the same time. Give some notes to the other hand.")
            fingers = [n["finger"] for n in g if n["finger"]]
            if len(fingers) != len(set(fingers)):
                raise EditorError("Two keys together have the same finger. Change one of the fingers.")
            ordered = [n["finger"] for n in g if n["finger"]]  # g is sorted by pitch (low to high)
            want = sorted(ordered) if hand == "R" else sorted(ordered, reverse=True)
            if ordered != want:
                raise EditorError("The fingers of keys together are in the wrong order. "
                                  "Give the higher finger numbers to the keys on the "
                                  + ("right." if hand == "R" else "left."))
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    end = max(n["start"] + n["dur"] for n in notes)

    sections = []
    for s in raw.get("sections") or []:
        if not isinstance(s, dict):
            continue
        a = _number(s.get("start"), "A part has no start. Set the parts again.")
        b = _number(s.get("end"), "A part has no end. Set the parts again.")
        name = s.get("name") if isinstance(s.get("name"), str) and s.get("name").strip() else ""
        sections.append({"name": name, "start": round(a, 4), "end": round(b, 4)})
    sections.sort(key=lambda s: s["start"])
    # Parts after the last note go away (notes were removed at the end of the song).
    sections = [s for s in sections if s["start"] < end - EPS]
    for i, s in enumerate(sections):
        if s["start"] < 0 or s["end"] <= s["start"] + EPS:
            raise EditorError("A part ends before it starts. Set the parts again.")
        if i and s["start"] < sections[i - 1]["end"] - EPS:
            raise EditorError("Two parts are at the same place. Set the parts again.")
        name = s["name"].strip()[:40]
        s["name"] = name if name and not re.fullmatch(r"Part \d+", name) else f"Part {i + 1}"

    loop = raw.get("loop")
    clean_loop = None
    if isinstance(loop, dict):
        a = _number(loop.get("start"), "Set the start of the loop.")
        b = _number(loop.get("end"), "Set the end of the loop.")
        if not 0 <= a < b - EPS:
            raise EditorError("The loop ends before it starts. Set the loop again.")
        if a >= end - EPS:
            raise EditorError("The loop starts after the last note. Set the loop again.")
        clean_loop = {"start": round(a, 4), "end": round(min(b, end), 4)}

    ts = raw.get("time_signature")
    if not (isinstance(ts, list) and len(ts) == 2 and all(isinstance(x, int) and x > 0 for x in ts)):
        ts = [4, 4]
    return {"title": title.strip()[:80], "bpm": round(bpm, 2), "key": key, "notes": notes,
            "sections": sections, "loop": clean_loop, "time_signature": ts, "end": end}


def prepare(raw: dict, original: dict | None, user_level: int) -> dict:
    """The song to save: the checked edit + fingers for new notes, hand positions, the chords,
    the difficulty and the level. Keeps the other fields of the original song."""
    edit = check(raw)
    notes = edit["notes"]
    if any(n["finger"] is None for n in notes):
        auto = copy.deepcopy(notes)
        for n in auto:
            n["finger"] = None
        song_level = int((original or {}).get("level") or 1)
        fingering.finger_song(auto, beginner=user_level <= 3 and song_level <= 3)
        for n, a in zip(notes, auto):
            if n["finger"] is None:
                n["finger"] = a["finger"]
    for i, n in enumerate(notes):
        n["id"] = i
    positions = []
    for hand in ("R", "L"):
        mine = [n for n in notes if n["hand"] == hand]
        if mine:
            positions += fingering.positions_from_fingers(mine, hand)
    song = {k: v for k, v in (original or {}).items() if k not in ("end",)}
    bar = float(edit["time_signature"][0])
    song.update({"title": edit["title"], "bpm": edit["bpm"], "key": edit["key"] or theory.detect_key(notes),
                 "time_signature": edit["time_signature"], "notes": notes, "sections": edit["sections"],
                 "hand_positions": positions, "chords": theory.chords_for_notes(notes, bar, edit["end"])})
    if edit["loop"]:
        song["loop"] = edit["loop"]
    else:
        song.pop("loop", None)
    diff = difficulty.analyze(song)
    song["difficulty"] = diff
    song["level"] = max(1, min(10, diff["level"]))
    song.setdefault("source", "midi")
    return song


def copy_id(title: str, original_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "song"
    digest = hashlib.sha1(f"{original_id}:{title}:{json.dumps(title)}".encode()).hexdigest()[:6]
    return f"my-{slug}-copy-{digest}"


def save(raw: dict, song_id: str, as_copy: bool, user_level: int) -> dict:
    """Save an edit. A built-in song needs as_copy. Returns the saved (validated) song."""
    original = songs.get(song_id)
    if original is None:
        raise EditorError("The app cannot find this song.")
    user = songs.is_user_song(song_id)
    if not as_copy and not user:
        raise EditorError('You cannot change a song of the app. Select "Save as my copy".')
    song = prepare(raw, original, user_level)
    if as_copy:
        title = song["title"]
        if title == original["title"]:
            title = f"{title} (my copy)"[:80]
        song["title"] = title
        song["id"] = copy_id(title, song_id)
        song["copy_of"] = song_id
        if original.get("source") in ("builtin", "course"):
            song["source"] = "copy"
        song.pop("order", None)
    else:
        song["id"] = song_id
    try:
        clean = songs.validate(song)
    except songs.SongError:
        # The hand positions from unusual fingers can fail the check: make them from the
        # automatic fingering of the same notes instead (the fingers stay as the user set them).
        auto = copy.deepcopy(song["notes"])
        for n in auto:
            n["finger"] = None
        song["hand_positions"] = fingering.finger_song(auto, beginner=False)["hand_positions"]
        try:
            clean = songs.validate(song)
        except songs.SongError:
            raise EditorError("The app cannot save the song. Check the notes and try again.") from None
    if as_copy:
        clean["id"] = songs.free_id(clean)  # never write over an earlier (edited) copy
    return songs.save_user_song(clean)
