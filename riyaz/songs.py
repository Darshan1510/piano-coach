"""Song files (PLAN 5.1): load, check and summarize songs.

A song is one JSON file in data/songs/. ``start`` and ``dur`` are in beats, not seconds:
the speed changes only the playback rate.

``hand_positions`` gives the hand outline. Each entry has ``hand``, ``start`` (beat) and
``thumb_pitch``. The 5 fingers sit on 5 white keys next to each other: up from the thumb for
the right hand, down from the thumb for the left hand. An entry can also give ``keys``: the
key of each finger 1-5 (for a spread hand, for example C E F G A). This is an extension of
the PLAN 5.1 format (DECISIONS.md, Phase 2).
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from . import config, theory

log = logging.getLogger("riyaz.songs")

Song = dict[str, Any]
HANDS = ("R", "L")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class SongError(ValueError):
    """The song file is not correct."""


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SongError(f"{what} must be a number")
    return float(value)


def white_keys_from(thumb: int, hand: str) -> list[int]:
    """Keys of fingers 1-5 in a 5-finger position on white keys."""
    step = 1 if hand == "R" else -1
    keys = [thumb]
    p = thumb
    while len(keys) < 5:
        p += step
        if not theory.is_black(p):
            keys.append(p)
    return keys


def position_keys(pos: dict) -> list[int]:
    """Key (pitch) of each finger 1-5 for one hand position."""
    if pos.get("keys"):
        return list(pos["keys"])
    return white_keys_from(pos["thumb_pitch"], pos["hand"])


def validate(raw: Any) -> Song:
    """Check a song and return a clean copy (notes sorted by start, then pitch)."""
    if not isinstance(raw, dict):
        raise SongError("song must be a JSON object")
    song_id = raw.get("id")
    if not isinstance(song_id, str) or not _ID_RE.match(song_id):
        raise SongError("id must be lower-case letters, digits and '-'")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SongError("title is missing")
    bpm = _num(raw.get("bpm"), "bpm")
    if not 20 <= bpm <= 300:
        raise SongError("bpm must be 20-300")
    ts = raw.get("time_signature", [4, 4])
    if (not isinstance(ts, list) or len(ts) != 2 or not all(isinstance(x, int) and x > 0 for x in ts)):
        raise SongError("time_signature must be [beats, unit]")
    level = raw.get("level", 1)
    if not isinstance(level, int) or not 1 <= level <= 10:
        raise SongError("level must be 1-10")

    notes_in = raw.get("notes")
    if not isinstance(notes_in, list) or not notes_in:
        raise SongError("notes are missing")
    notes = []
    for i, n in enumerate(notes_in):
        if not isinstance(n, dict):
            raise SongError(f"note {i} must be an object")
        pitch = n.get("pitch")
        if not isinstance(pitch, int) or not config.KEY_LOW <= pitch <= config.KEY_HIGH:
            raise SongError(f"note {i}: pitch must be {config.KEY_LOW}-{config.KEY_HIGH} (61 keys)")
        start, dur = _num(n.get("start"), f"note {i} start"), _num(n.get("dur"), f"note {i} dur")
        if start < 0 or dur <= 0:
            raise SongError(f"note {i}: start must be >= 0 and dur > 0")
        hand = n.get("hand")
        if hand not in HANDS:
            raise SongError(f"note {i}: hand must be R or L")
        finger = n.get("finger")
        if finger is not None and (not isinstance(finger, int) or not 1 <= finger <= 5):
            raise SongError(f"note {i}: finger must be 1-5")
        vel = n.get("vel", 80)
        if not isinstance(vel, int) or not 1 <= vel <= 127:
            raise SongError(f"note {i}: vel must be 1-127")
        notes.append({"id": n.get("id", i), "pitch": pitch, "start": start, "dur": dur, "hand": hand,
                      "finger": finger, "vel": vel})
    ids = [n["id"] for n in notes]
    if len(set(ids)) != len(ids):
        raise SongError("note ids must be different")
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    end = max(n["start"] + n["dur"] for n in notes)

    sections = []
    for i, s in enumerate(raw.get("sections") or []):
        name = s.get("name") if isinstance(s, dict) else None
        if not isinstance(name, str):
            raise SongError(f"section {i}: name is missing")
        a, b = _num(s.get("start"), f"section {i} start"), _num(s.get("end"), f"section {i} end")
        if not 0 <= a < b:
            raise SongError(f"section {i}: start must be before end")
        sections.append({"name": name, "start": a, "end": b})

    positions = []
    for i, p in enumerate(raw.get("hand_positions") or []):
        if not isinstance(p, dict) or p.get("hand") not in HANDS:
            raise SongError(f"hand position {i}: hand must be R or L")
        thumb = p.get("thumb_pitch")
        # A hand at the end of the keyboard can have fingers past the last key (imported songs).
        if not isinstance(thumb, int) or not config.KEY_LOW - 12 <= thumb <= config.KEY_HIGH + 12:
            raise SongError(f"hand position {i}: thumb_pitch is not on the keyboard")
        pos = {"hand": p["hand"], "start": _num(p.get("start"), f"hand position {i} start"), "thumb_pitch": thumb}
        keys = p.get("keys")
        if keys is not None:
            if (not isinstance(keys, list) or len(keys) != 5 or not all(isinstance(k, int) for k in keys)
                    or keys[0] != thumb):
                raise SongError(f"hand position {i}: keys must be 5 pitches, thumb first")
            order = keys if p["hand"] == "R" else keys[::-1]
            if order != sorted(set(order)):
                raise SongError(f"hand position {i}: keys must go away from the thumb")
            pos["keys"] = keys
        positions.append(pos)
    positions.sort(key=lambda p: (p["hand"], p["start"]))

    chords = []
    for c in raw.get("chords") or []:
        if isinstance(c, dict) and isinstance(c.get("name"), str):
            chords.append({"start": _num(c.get("start"), "chord start"), "dur": _num(c.get("dur"), "chord dur"),
                           "name": c["name"]})

    song = {
        "id": song_id, "title": title.strip(), "source": raw.get("source", "builtin"), "bpm": bpm,
        "time_signature": ts, "key": raw.get("key", ""), "level": level, "notes": notes,
        "chords": chords, "sections": sections, "hand_positions": positions, "end": end,
    }
    order = raw.get("order", 99)  # place in the song list inside its level
    song["order"] = order if isinstance(order, int) else 99
    if isinstance(raw.get("credit"), str):
        song["credit"] = raw["credit"]
    # Imported songs (Phase 3a): the difficulty check and the import facts.
    # Phase 5a: easy versions (``version_of``), the editor's loop (``loop``), copies (``copy_of``).
    for name in ("difficulty", "import", "version_of"):
        if isinstance(raw.get(name), dict):
            song[name] = raw[name]
    loop = raw.get("loop")
    if isinstance(loop, dict):
        a, b = _num(loop.get("start"), "loop start"), _num(loop.get("end"), "loop end")
        if not 0 <= a < b:
            raise SongError("loop: start must be before end")
        song["loop"] = {"start": a, "end": b}
    if isinstance(raw.get("copy_of"), str):
        song["copy_of"] = raw["copy_of"]
    return song


def save_user_song(song: Song) -> Song:
    """Write a song JSON file in the user songs folder (atomic). Returns the song."""
    folder = config.user_songs_path()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{song['id']}.json"
    out = {k: v for k, v in song.items() if k != "end"}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=1), encoding="utf-8")
    tmp.replace(path)
    invalidate()
    return song


def _same_song(a: dict, b: dict) -> bool:
    def key(s):
        notes = [(n.get("pitch"), round(float(n.get("start", 0)), 4), round(float(n.get("dur", 0)), 4),
                  n.get("hand"), n.get("finger")) for n in s.get("notes") or []]
        return (s.get("title"), s.get("bpm"), s.get("key"), sorted(notes, key=str),
                [(p.get("start"), p.get("end"), p.get("name")) for p in s.get("sections") or []], s.get("loop"))
    return key(a) == key(b)


def free_id(song: Song) -> str:
    """The id to save a new user song with: its own id when no other file has that id (or the
    file has the same song), else the id with "-2", "-3", ... (an edited version or copy is
    never written over)."""
    folder = config.user_songs_path()
    base = song["id"]
    for i in range(1, 1000):
        cand = base if i == 1 else f"{base[: 63 - len(str(i))].rstrip('-')}-{i}"
        if cand in _builtin_ids():
            continue
        path = folder / f"{cand}.json"
        if not path.is_file():
            return cand
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(old, dict) and _same_song(old, song):
            return cand
    raise SongError("too many songs with the same id")


def is_user_song(song_id: str) -> bool:
    """True if the song file is in the user songs folder (imported, a version or a copy)."""
    return bool(_ID_RE.match(song_id or "")) and (config.user_songs_path() / f"{song_id}.json").is_file() \
        and song_id not in _builtin_ids()


def _builtin_ids() -> set[str]:
    folder = config.songs_path()
    return {p.stem for p in folder.glob("*.json")} if folder.is_dir() else set()


def song_dirs() -> list[Path]:
    """Built-in songs first (an imported song cannot replace a built-in song), then the others."""
    dirs = [config.songs_path()]
    extra = config.extra_song_dir()
    if extra is not None:
        dirs.append(extra)
    dirs.append(config.user_songs_path())
    return dirs


def load_file(path: Path) -> Song:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SongError(f"{path.name}: {exc}") from exc
    return validate(raw)


_cache_lock = threading.Lock()
_cache: dict = {"sig": None, "songs": {}}


def _signature() -> tuple:
    """The song files (folder, name, change time, size). A new, changed or removed file changes it."""
    out = []
    for folder in song_dirs():
        files = []
        if folder.is_dir():
            for path in sorted(folder.glob("*.json")):
                try:
                    st = path.stat()
                except OSError:
                    continue
                files.append((path.name, st.st_mtime_ns, st.st_size))
        out.append((str(folder), tuple(files)))
    return tuple(out)


def invalidate() -> None:
    """Read the song files again at the next load_all() (after an import or a save)."""
    with _cache_lock:
        _cache["sig"] = None


def load_all() -> dict[str, Song]:
    """All songs by id. A bad file is skipped (and logged).

    The songs are cached until a song file changes (or invalidate()). The dict is a new dict, but
    the songs in it are shared: do not change them.
    """
    sig = _signature()
    with _cache_lock:
        if _cache["sig"] == sig:
            return dict(_cache["songs"])
    songs: dict[str, Song] = {}
    for folder in song_dirs():
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                song = load_file(path)
            except SongError as exc:
                log.warning("Song file skipped: %s", exc)
                continue
            songs.setdefault(song["id"], song)
    with _cache_lock:
        _cache["sig"], _cache["songs"] = sig, songs
    return dict(songs)


def get(song_id: str) -> Song | None:
    return load_all().get(song_id)


def hands_of(song: Song) -> list[str]:
    present = {n["hand"] for n in song["notes"]}
    return [h for h in HANDS if h in present]


def summary(song: Song, user_level: int = config.USER_LEVEL_DEFAULT,
            versions: dict[str, list[Song]] | None = None) -> dict:
    """The data for one song card. Imported songs also get the difficulty card text (PLAN 8.4).

    An easy version (Phase 5a) has ``version_of``. A song with an easy version that fits the
    user's level says "You can play the easy version now." and names the version (``easy``).
    """
    out = {
        "id": song["id"], "title": song["title"], "level": song["level"], "bpm": song["bpm"],
        "hands": hands_of(song), "beats": song["end"],
        "seconds": round(song["end"] * 60.0 / song["bpm"]), "note_count": len(song["notes"]),
        "notes_by_hand": {h: sum(1 for n in song["notes"] if n["hand"] == h) for h in hands_of(song)},
        "sections": song["sections"], "order": song["order"], "source": song["source"],
        "user_song": song["source"] not in ("builtin", "course"),
    }
    if isinstance(song.get("difficulty"), dict):
        from .difficulty import card_text

        out["difficulty"] = {**card_text(song["difficulty"], user_level), "skills": song["difficulty"].get("skills", [])}
    meta = song.get("version_of")
    if isinstance(meta, dict):
        from .simplify import changed_text

        out["version_of"] = {"id": meta.get("id"), "title": meta.get("title"), "level": meta.get("level"),
                             "changed": meta.get("changed") or 0, "changed_text": changed_text(meta)}
    elif versions is not None and out.get("difficulty") and not out["difficulty"]["playable"]:
        fits = [v for v in versions.get(song["id"], []) if v["level"] <= user_level]
        if fits:
            best = max(fits, key=lambda v: (v["version_of"].get("level") or 0, v["level"]))
            out["easy"] = {"id": best["id"], "title": best["title"], "level": best["level"]}
            out["difficulty"]["text"] = "You can play the easy version now."
            out["difficulty"]["easy"] = True
    return out


def list_summaries(user_level: int = config.USER_LEVEL_DEFAULT) -> list[dict]:
    from .simplify import versions_of

    all_songs = load_all()
    versions = versions_of(all_songs)
    return sorted((summary(s, user_level, versions) for s in all_songs.values()),
                  key=lambda s: (s["source"] != "builtin", s["level"], s["order"], s["title"]))
