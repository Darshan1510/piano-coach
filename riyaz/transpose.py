"""Transpose trainer (PLAN 3 "Advanced", 8.3 Level 10 "change key", Phase 6).

A learned song, moved to a new key family: every note moves by the same number of keys (a
"shift" of -6 to +5 semitones, then one octave up or down when the song does not fit on the 61
keys). The chord names and the key name move too. The fingering is made again (riyaz/fingering.py,
no beginner mode: a Level 10 user knows "thumb under").

A transposed song is a separate song (``source`` "simplified") with ``version_of`` =
{"id", "title", "kind": "transpose", "shift", "key"}. It is saved in the user songs folder (the
app data folder), like an easy version. The course (riyaz/course.py) counts a done run of a
transposed song for the "transpose" task of the source song (Level 10).
"""

from __future__ import annotations

import copy

from . import config, difficulty, leadsheet, simplify, songs, theory

EPS = 1e-6
CHOICES_MAX = 6  # keys that the trainer offers (fewest black keys first)


class TransposeError(ValueError):
    """The text is for the user."""


def _fits(song: dict, shift: int) -> bool:
    return all(config.KEY_LOW <= n["pitch"] + shift <= config.KEY_HIGH for n in song["notes"])


def octave_shift(song: dict, shift: int) -> int | None:
    """The shift (shift, shift - 12 or shift + 12) that keeps every note on the keyboard and moves
    the least. None if no shift fits."""
    for s in sorted((shift, shift - 12, shift + 12), key=abs):
        if _fits(song, s):
            return s
    return None


def key_after(song: dict, shift: int) -> tuple[int, str]:
    tonic, mode = simplify.song_key(song)
    return (tonic + shift) % 12, mode


def key_text(key: str, unlocked) -> str:
    """A key name for the page (PLAN 7.4): "G major" only when "major" is unlocked, else
    "G (happy sound)" / "A (sad sound)". The song data keeps the full key name."""
    from .course import plain_text

    tonic, _, mode = (key or "").partition(" ")
    if mode == "major":
        return plain_text(f"{tonic} [[major_minor|major|(happy sound)]]", set(unlocked))
    if mode == "minor":
        return plain_text(f"{tonic} [[major_minor|minor|(sad sound)]]", set(unlocked))
    return key or ""


def chord_name_after(name: str, shift: int) -> str:
    p = leadsheet.parse(name)
    if p is None:
        return name
    root, suffix, bass = p
    out = theory.chord_root_name((root + shift) % 12) + suffix
    if bass is not None:
        out += "/" + theory.chord_root_name((bass + shift) % 12)
    return out


def source_of(song: dict) -> dict:
    """A transposed song -> its source song (when the source is still there)."""
    meta = song.get("version_of")
    if isinstance(meta, dict) and meta.get("kind") == "transpose":
        src = songs.get(str(meta.get("id")))
        if src is not None:
            return src
    return song


def choices(song: dict) -> list[dict]:
    """The new keys for a song: [{"shift", "key", "black_keys"}], fewest black keys first."""
    src = source_of(song)
    tonic, mode = simplify.song_key(src)
    out = []
    for shift in range(-6, 6):
        if shift == 0:
            continue
        s = octave_shift(src, shift)
        if s is None:
            continue
        black = sum(1 for n in src["notes"] if theory.is_black(n["pitch"] + s))
        out.append({"shift": shift, "key": theory.key_name((tonic + shift) % 12, mode), "black_keys": black})
    out.sort(key=lambda c: (c["black_keys"], abs(c["shift"])))
    return out[:CHOICES_MAX]


def _slug(text: str) -> str:
    return text.lower().replace("#", "s").replace(" ", "-")


def version_id(source_id: str, key: str) -> str:
    base = source_id if source_id.startswith("my-") else f"my-{source_id}"
    tag = f"-in-{_slug(key)}"
    return base[: 64 - len(tag)].rstrip("-") + tag


def make(song: dict, shift: int) -> dict:
    """The song moved by `shift` semitones (-6..5, not 0). Returns a validated song (not saved)."""
    if not isinstance(shift, int) or isinstance(shift, bool) or not -6 <= shift <= 5 or shift == 0:
        raise TransposeError("Select a new key family for the song.")
    src = source_of(song)
    s = octave_shift(src, shift)
    if s is None:
        raise TransposeError("The song does not fit on the keyboard in this key family. Select a different one.")
    new_key = theory.key_name(*key_after(src, shift))
    out = copy.deepcopy({k: v for k, v in src.items() if k not in ("end", "difficulty", "import", "loop", "copy_of")})
    for n in out["notes"]:
        n["pitch"] += s
    out["chords"] = [{**c, "name": chord_name_after(c["name"], shift)} for c in src.get("chords") or []]
    out["key"] = new_key
    out["source"] = "simplified"
    simplify.finger_version(out, config.MAX_COURSE_LEVEL)
    diff = difficulty.analyze(out)
    out["difficulty"] = diff
    out["level"] = max(1, min(10, max(int(src.get("level", 1)), diff["level"])))
    out["title"] = f"{src['title']} (in {new_key.split()[0]})"[:80]  # no "major"/"minor" in a title
    out["id"] = version_id(src["id"], new_key)
    out["version_of"] = {"id": src["id"], "title": src["title"], "kind": "transpose", "shift": s,
                         "key": new_key, "from_key": src.get("key") or theory.key_name(*simplify.song_key(src)),
                         "level": None, "changed": 0}
    out.pop("order", None)
    return songs.validate(out)


def save(song: dict) -> dict:
    return simplify.save(song)


def versions(source_id: str, all_songs: dict | None = None) -> list[dict]:
    all_songs = songs.load_all() if all_songs is None else all_songs
    return [s for s in all_songs.values()
            if isinstance(s.get("version_of"), dict) and s["version_of"].get("kind") == "transpose"
            and s["version_of"].get("id") == source_id]


def ensure_version(source: dict) -> dict:
    """A transposed version of the song (the one saved before, else a new one in the easiest key)."""
    have = versions(source["id"])
    if have:
        return sorted(have, key=lambda v: v["id"])[0]
    opts = choices(source)
    if not opts:
        raise TransposeError("The song does not fit on the keyboard in a new key family.")
    return save(make(source, opts[0]["shift"]))
