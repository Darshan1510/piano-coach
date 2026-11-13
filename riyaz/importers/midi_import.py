"""MIDI file import (PLAN 11.1).

1. Read the file with mido. Merge the tempo map of all tracks; convert ticks to beats.
2. Track list: one part for each track and channel that has notes, with the note count and the
   instrument name. Default: piano parts. Drums (channel 10) are never a default.
3. Hand split (riyaz/handsplit.py), fingering (riyaz/fingering.py), chords and key (theory.py),
   difficulty (riyaz/difficulty.py).
4. Quantize option: 1/8 or 1/16 notes.
5. Parts of the song ("Part 1", "Part 2"): at long pauses, else every 4 bars.
6. Save the song JSON in the user data folder; keep the original .mid file next to it.

Beats: one beat of a song is the note value of the time signature (a quarter note in 4/4, an
eighth note in 6/8), so that the count-in and the click follow the time signature. The song
format has one speed (``bpm``): the app uses the tempo that the file uses for most of its time.
Tempo changes in the file are counted, but the song plays at one speed (DECISIONS.md).

All error texts are for the user (ASD-STE100, PLAN 7.4 words). A bad file never crashes the app.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field

import mido

from .. import config, difficulty, fingering, handsplit, songs, theory

log = logging.getLogger("riyaz.import")

DRUM_CHANNEL = 9  # MIDI channel 10 (mido counts from 0)
MIN_DUR_QUARTERS = 1 / 32
EPS = 1e-6

# General MIDI instrument families (program // 8).
GM_FAMILIES = ("Piano", "Bell sounds", "Organ", "Guitar", "Bass", "Strings", "Strings group", "Brass",
               "Reed", "Flute", "Synth lead", "Synth pad", "Synth effects", "World", "Percussion",
               "Sound effects")


class MidiImportError(ValueError):
    """The text is for the user."""


@dataclass
class Part:
    index: int
    track: int
    channel: int  # 0-15
    name: str
    instrument: str
    program: int | None
    notes: list[tuple[int, int, int, int]] = field(default_factory=list)  # (start tick, end tick, pitch, vel)

    @property
    def drums(self) -> bool:
        return self.channel == DRUM_CHANNEL

    @property
    def piano(self) -> bool:
        return not self.drums and (self.program is None or self.program < 8)


@dataclass
class ParsedMidi:
    filename: str
    data: bytes
    ticks_per_beat: int
    parts: list[Part]
    tempos: list[tuple[int, int]]  # (tick, microseconds per quarter note)
    time_signature: tuple[int, int]
    title: str
    end_tick: int
    key_signature: str | None = None  # mido key text, for example "G" or "Em"


# ------------------------------------------------------------------------------------- reading


def parse(data: bytes, filename: str = "song.mid") -> ParsedMidi:
    """Read a MIDI file (bytes). Raises MidiImportError with a text for the user."""
    if not data:
        raise MidiImportError("The file is empty. Select a different file.")
    if len(data) > config.IMPORT_MAX_BYTES:
        mb = config.IMPORT_MAX_BYTES // (1024 * 1024)
        raise MidiImportError(f"The file is too large. The limit is {mb} MB. Select a smaller file.")
    if data[:4] != b"MThd":
        raise MidiImportError("This file is not a MIDI file. Select a file that ends in .mid or .midi.")
    try:
        mid = mido.MidiFile(file=io.BytesIO(data), clip=True)
    except Exception as exc:  # mido raises many types (OSError, EOFError, ValueError, KeyError ...)
        log.info("MIDI read error: %r", exc)
        raise MidiImportError("The app cannot read this MIDI file. The file is damaged. "
                              "Select a different file.") from None
    if mid.type == 2:
        raise MidiImportError("The app cannot use this type of MIDI file (type 2). Select a different file.")
    tpb = mid.ticks_per_beat
    if not isinstance(tpb, int) or tpb <= 0:
        raise MidiImportError("The app cannot use the timing of this MIDI file. Select a different file.")
    if len(mid.tracks) > config.IMPORT_MAX_TRACKS:
        raise MidiImportError(f"The file has too many tracks. The limit is {config.IMPORT_MAX_TRACKS}.")

    tempos: list[tuple[int, int]] = []
    time_sigs: list[tuple[int, int, int]] = []
    key_sigs: list[tuple[int, str]] = []
    parts: dict[tuple[int, int], Part] = {}
    found: list[tuple[int, int, str, str, int | None, list]] = []  # (track, channel, name, inst, program, notes)
    file_programs: dict[int, tuple[int, int, int]] = {}  # channel -> (tick, track, program), first in the file
    total = 0  # every note_on with velocity > 0 (also a key pressed again, or a note with no note off)
    end_tick = 0
    title = ""
    try:
        for ti, track in enumerate(mid.tracks):
            tick = 0
            name = ""
            inst_name = ""
            programs: dict[int, int] = {}
            open_notes: dict[tuple[int, int], list[tuple[int, int]]] = {}
            part_notes: dict[int, list[tuple[int, int, int, int]]] = {}
            for msg in track:
                tick += msg.time
                if msg.type == "set_tempo":
                    tempos.append((tick, msg.tempo))
                elif msg.type == "time_signature":
                    time_sigs.append((tick, msg.numerator, msg.denominator))
                elif msg.type == "key_signature":
                    key_sigs.append((tick, str(msg.key)))
                elif msg.type == "track_name":
                    name = name or str(msg.name).strip()
                elif msg.type == "instrument_name":
                    inst_name = inst_name or str(msg.name).strip()
                elif msg.type == "program_change":
                    programs.setdefault(msg.channel, msg.program)
                    if msg.channel not in file_programs or tick < file_programs[msg.channel][0]:
                        file_programs[msg.channel] = (tick, ti, msg.program)
                elif msg.type == "note_on" and msg.velocity > 0:
                    total += 1
                    if total > config.IMPORT_MAX_RAW_NOTES:
                        raise MidiImportError(f"The file has too many notes. The limit is "
                                              f"{config.IMPORT_MAX_RAW_NOTES}. Select a shorter song.")
                    stack = open_notes.setdefault((msg.channel, msg.note), [])
                    if stack:  # the same key again before its note off: end the first note here
                        s, v = stack.pop(0)
                        part_notes.setdefault(msg.channel, []).append((s, tick, msg.note, v))
                    stack.append((tick, msg.velocity))
                elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                    stack = open_notes.get((msg.channel, msg.note))
                    if stack:
                        s, v = stack.pop(0)
                        part_notes.setdefault(msg.channel, []).append((s, tick, msg.note, v))
            for (ch, pitch), stack in open_notes.items():  # notes with no note off: end at the track end
                for s, v in stack:
                    part_notes.setdefault(ch, []).append((s, max(tick, s + 1), pitch, v))
            end_tick = max(end_tick, tick)
            if ti == 0 and name and not part_notes:
                title = name
            for ch in sorted(part_notes):
                found.append((ti, ch, name, inst_name, programs.get(ch), sorted(part_notes[ch])))
        # A program change can be in a different track (for example a "conductor" track of a type 1
        # file): the track's own program for the channel wins, else the first one in the file.
        for ti, ch, name, inst_name, prog, notes in found:
            if prog is None and ch in file_programs:
                prog = file_programs[ch][2]
            if ch == DRUM_CHANNEL:
                instrument = "Drums"
            elif inst_name:
                instrument = inst_name[:40]
            elif prog is not None:
                instrument = GM_FAMILIES[prog // 8]
            else:
                instrument = "Piano"
            parts[(ti, ch)] = Part(index=0, track=ti, channel=ch, name=name[:40], instrument=instrument,
                                   program=prog, notes=notes)
    except MidiImportError:
        raise
    except Exception as exc:
        log.info("MIDI content error: %r", exc)
        raise MidiImportError("The app cannot read this MIDI file. The file is damaged. "
                              "Select a different file.") from None

    ordered = [parts[k] for k in sorted(parts)]
    if not ordered:
        raise MidiImportError("This file has no notes. Select a different file.")
    for i, p in enumerate(ordered):
        p.index = i
        if not p.name:
            p.name = f"Track {p.track + 1}" if len({q.track for q in ordered}) > 1 else f"Channel {p.channel + 1}"
    # Stable sort on the tick only: at the same tick, the later event (later in the track, or in a
    # later track) wins, as in a MIDI player.
    tempos.sort(key=lambda t: t[0])
    time_sigs.sort(key=lambda t: t[0])
    key_sigs.sort(key=lambda t: t[0])
    ts = (time_sigs[0][1], time_sigs[0][2]) if time_sigs else (4, 4)
    if ts[0] <= 0 or ts[1] not in (1, 2, 4, 8, 16, 32):
        ts = (4, 4)
    return ParsedMidi(filename=filename, data=data, ticks_per_beat=tpb, parts=ordered, tempos=tempos,
                      time_signature=ts, title=title, end_tick=end_tick,
                      key_signature=key_sigs[0][1] if key_sigs else None)


def track_list(parsed: ParsedMidi) -> list[dict]:
    """The track list for the import screen."""
    pianos = [p for p in parsed.parts if p.piano]
    defaults = pianos or [p for p in parsed.parts if not p.drums]
    out = []
    for p in parsed.parts:
        pitches = [n[2] for n in p.notes]
        out.append({"index": p.index, "name": p.name, "instrument": p.instrument, "channel": p.channel + 1,
                    "note_count": len(p.notes), "drums": p.drums, "default": p in defaults,
                    "low": min(pitches), "high": max(pitches)})
    return out


def main_tempo(parsed: ParsedMidi) -> tuple[int, int]:
    """(microseconds per quarter note that lasts the most ticks, number of tempo changes)."""
    first = min(n[0] for p in parsed.parts for n in p.notes)
    last = max(n[1] for p in parsed.parts for n in p.notes)
    tempos = [(0, 500000)] + [t for t in parsed.tempos]
    # The last tempo at or before each tick wins; drop tempos that are replaced at the same tick.
    merged: list[tuple[int, int]] = []
    for tick, tempo in tempos:
        if merged and merged[-1][0] == tick:
            merged[-1] = (tick, tempo)
        else:
            merged.append((tick, tempo))
    length: dict[int, int] = {}
    for i, (tick, tempo) in enumerate(merged):
        nxt = merged[i + 1][0] if i + 1 < len(merged) else last
        a, b = max(tick, first), min(nxt, last)
        if b > a:
            length[tempo] = length.get(tempo, 0) + (b - a)
    if not length:
        return merged[-1][1], 0
    changes = sum(1 for (_t, a), (tick, b) in zip(merged, merged[1:]) if a != b and first < tick < last)
    return max(length, key=lambda t: (length[t], -t)), changes


# ------------------------------------------------------------------------------------ the song


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:40].strip("-") or "song"


def default_title(parsed: ParsedMidi) -> str:
    """The file name (the name in the file is often a track name, for example "control track")."""
    stem = os.path.splitext(os.path.basename(parsed.filename))[0]
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return (stem[:1].upper() + stem[1:])[:60] if stem else "My song"


def _fit_keyboard(pitch: int) -> tuple[int, bool]:
    """Move a note that is not on the 61 keys by octaves onto the keyboard."""
    moved = False
    while pitch < config.KEY_LOW:
        pitch += 12
        moved = True
    while pitch > config.KEY_HIGH:
        pitch -= 12
        moved = True
    return pitch, moved


def detect_sections(notes: list[dict], bar: float, end: float, every: int = config.SECTION_BARS) -> list[dict]:
    """Song parts: split at a pause of 1 bar or more, else every 4 bars. Names "Part 1", "Part 2"."""
    if not notes or bar <= 0:
        return []
    total_bars = max(1, math.ceil(end / bar - EPS))
    cuts = {0}
    last_end = None
    for n in sorted(notes, key=lambda n: n["start"]):
        if last_end is not None and n["start"] - last_end >= bar - EPS:
            cuts.add(int(math.floor(n["start"] / bar + EPS)))
        last_end = n["start"] + n["dur"] if last_end is None else max(last_end, n["start"] + n["dur"])
    cuts_sorted = sorted(c for c in cuts if c < total_bars) + [total_bars]
    bounds: list[int] = []
    for a, b in zip(cuts_sorted, cuts_sorted[1:]):
        bounds.extend(range(a, b, every))
    bounds.append(total_bars)
    # A last part of less than 2 bars joins the part before it (not when a long pause starts it).
    if len(bounds) > 2 and bounds[-1] - bounds[-2] < 2 and bounds[-2] not in cuts:
        bounds.pop(-2)
    out = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:])):
        out.append({"name": f"Part {i + 1}", "start": round(a * bar, 6), "end": round(b * bar, 6)})
    return out


KEY_SIG_MARGIN = 0.05  # the key signature in the file wins when it is this close to the best key


def song_key(notes: list[dict], key_signature: str | None) -> str:
    """Key from the notes (Krumhansl-Schmuckler). The file's key signature breaks a near tie."""
    cands = theory.key_candidates(notes)
    if not cands:
        return ""
    best = cands[0]
    if key_signature:
        mode = "minor" if key_signature.endswith("m") else "major"
        name = key_signature[:-1] if mode == "minor" else key_signature
        names = theory.SHARP_NAMES if "#" in name else theory.FLAT_NAMES
        if name in names:
            tonic = names.index(name)
            for c in cands[:3]:
                if c[1] == tonic and c[2] == mode and best[0] - c[0] <= KEY_SIG_MARGIN:
                    best = c
                    break
    return theory.key_name(best[1], best[2])


def _limit_chord(group: list[dict]) -> list[dict]:
    """At most 5 keys at once in one hand: keep the 2 lowest and the 3 highest keys."""
    if len(group) <= 5:
        return group
    g = sorted(group, key=lambda n: n["pitch"])
    return g[:2] + g[-3:]


BEGINNER_MAX_LEVEL = 3  # beginner fingering for Levels 1-3 (PLAN 5.3)
BPM_MIN, BPM_MAX = 20.0, 300.0


def song_beat(num: int, den: int, qpm: float) -> tuple[int, int, float]:
    """(numerator, denominator, song beats for each quarter note) for the song.

    The beat is the note value of the time signature (den), so the click follows the time
    signature. If that speed is not in 20-300 beats a minute, the beat is a quarter note, then a
    half note or an eighth note, and the time signature changes to match: one bar stays the same
    length (6/8 at 180 quarter notes a minute -> 3/4). If no beat fits, the time signature stays and
    the speed is clamped to 20-300 (for example 3/8 at 180 quarter notes a minute).
    """
    native = den / 4
    if BPM_MIN <= qpm * native <= BPM_MAX:
        return num, den, native
    bar_quarters = num * 4 / den
    for factor in (1.0, 0.5, 2.0, 0.25, 4.0):
        beats = bar_quarters * factor
        if (BPM_MIN <= qpm * factor <= BPM_MAX and beats >= 1
                and abs(beats - round(beats)) < EPS):
            return int(round(beats)), int(4 * factor), factor
    return num, den, native


def build_song(parsed: ParsedMidi, parts: list[int] | None = None, swap: bool = False,
               quantize: int | None = None, title: str | None = None,
               user_level: int = config.USER_LEVEL_DEFAULT) -> dict:
    """Make the song (PLAN 5.1 format) from the selected parts. Raises MidiImportError."""
    if parts is None:
        parts = [t["index"] for t in track_list(parsed) if t["default"]]
    if not isinstance(parts, list) or not parts:
        raise MidiImportError("Select one or more tracks.")
    by_index = {p.index: p for p in parsed.parts}
    if not all(isinstance(i, int) and not isinstance(i, bool) and i in by_index for i in parts):
        raise MidiImportError("The app cannot find this track. Select a different track.")
    parts = list(dict.fromkeys(parts))
    if quantize not in (None, 0) + config.IMPORT_QUANTIZE:
        raise MidiImportError("Select Off, Large steps or Small steps.")
    count = sum(len(by_index[i].notes) for i in parts)
    if count > config.IMPORT_MAX_NOTES:
        raise MidiImportError(f"The selected tracks have too many notes ({count}). The limit is "
                              f"{config.IMPORT_MAX_NOTES}. Select fewer tracks or a shorter song.")
    tempo, tempo_changes = main_tempo(parsed)
    qpm = 60_000_000 / tempo
    num, den, factor = song_beat(*parsed.time_signature, qpm)
    bpm = min(300.0, max(20.0, qpm * factor))
    tpb = parsed.ticks_per_beat
    grid = (4 / quantize) * factor if quantize else None
    min_dur = MIN_DUR_QUARTERS * factor

    def beats(tick: int) -> float:
        return tick / tpb * factor

    moved = 0
    part_notes: list[list[dict]] = []
    for idx in parts:
        lst = []
        for s, e, pitch, vel in by_index[idx].notes:
            pitch, was_moved = _fit_keyboard(pitch)
            moved += was_moved
            a, b = beats(s), beats(e)
            if grid:
                a = round(a / grid) * grid
                b = round(b / grid) * grid
                if b <= a + EPS:
                    b = a + grid
            elif b - a < min_dur:
                b = a + min_dur
            lst.append({"pitch": pitch, "start": round(a, 4), "dur": round(b - a, 4), "vel": max(1, min(127, vel)),
                        "hand": "R", "finger": None})
        part_notes.append(lst)

    # Same key at the same time (in all selected parts): keep the longest note.
    seen: dict[tuple[float, int], dict] = {}
    for lst in part_notes:
        for n in lst:
            k = (n["start"], n["pitch"])
            if k not in seen or n["dur"] > seen[k]["dur"]:
                seen[k] = n
    keep = {id(n) for n in seen.values()}
    part_notes = [[n for n in lst if id(n) in keep] for lst in part_notes]
    method = handsplit.assign_hands(part_notes, swap=swap)
    notes = [n for lst in part_notes for n in lst]
    if not notes:
        raise MidiImportError("The selected tracks have no notes. Select different tracks.")

    # A key that sounds again before its note ends: end the first note there (same hand).
    by_key: dict[tuple[str, int], list[dict]] = {}
    for n in notes:
        by_key.setdefault((n["hand"], n["pitch"]), []).append(n)
    for lst in by_key.values():
        lst.sort(key=lambda n: n["start"])
        for a, b in zip(lst, lst[1:]):
            if a["start"] + a["dur"] > b["start"] + EPS:
                a["dur"] = round(max(min_dur, b["start"] - a["start"]), 4)

    dropped = 0
    kept: list[dict] = []
    for hand in ("R", "L"):
        for g in handsplit.onsets([n for n in notes if n["hand"] == hand]):
            lim = _limit_chord(g)
            dropped += len(g) - len(lim)
            kept.extend(lim)
    notes = kept

    # Start at the bar of the first note. One bar = num song beats (song_beat keeps this true).
    bar = float(num)
    first = min(n["start"] for n in notes)
    shift = math.floor(first / bar + EPS) * bar
    for n in notes:
        n["start"] = round(n["start"] - shift, 4)
    notes.sort(key=lambda n: (n["start"], n["pitch"]))
    for i, n in enumerate(notes):
        n["id"] = i
    end = max(n["start"] + n["dur"] for n in notes)
    if end * 60.0 / bpm > config.IMPORT_MAX_MINUTES * 60:
        raise MidiImportError(f"The song is too long. The limit is {config.IMPORT_MAX_MINUTES} minutes. "
                              "Select a shorter song.")

    song: dict = {
        "title": (title or "").strip()[:80] or default_title(parsed),
        "source": "midi", "bpm": round(bpm, 2), "time_signature": [num, den],
        "notes": notes,
    }
    # Beginner mode is for Levels 1-3 (PLAN 5.3): a user above Level 3, or a song above Level 3,
    # gets the normal fingering.
    beginner = user_level <= BEGINNER_MAX_LEVEL
    fing = fingering.finger_song(notes, beginner=beginner)
    song["hand_positions"] = fing["hand_positions"]
    diff = difficulty.analyze(song)
    if diff["level"] > BEGINNER_MAX_LEVEL and any(m == "beginner" for m in fing["modes"].values()):
        for n in notes:
            n["finger"] = None
        fing = fingering.finger_song(notes, beginner=False)
        song["hand_positions"] = fing["hand_positions"]
        diff = difficulty.analyze(song)
    song["key"] = song_key(notes, parsed.key_signature)
    song["chords"] = theory.chords_for_notes(notes, bar, end)
    song["sections"] = detect_sections(notes, bar, end)
    song["level"] = max(1, min(10, diff["level"]))
    song["difficulty"] = diff
    digest = hashlib.sha1(parsed.data + json.dumps([parts, swap, quantize]).encode()).hexdigest()[:6]
    song["id"] = f"my-{_slug(song['title'])}-{digest}"
    song["import"] = {
        "file": os.path.basename(parsed.filename)[:120], "parts": parts, "method": method, "swap": bool(swap),
        "quantize": quantize or None, "fingering": fing["modes"], "moved_octave": moved,
        "dropped_notes": dropped, "tempo_changes": tempo_changes, "midi_bpm": round(qpm, 2),
    }
    return songs.validate(song)


def save(song: dict, data: bytes) -> dict:
    """Write <id>.json and the original <id>.mid in the user songs folder. Returns the song."""
    folder = config.user_songs_path()
    folder.mkdir(parents=True, exist_ok=True)
    base = folder / song["id"]
    out = {k: v for k, v in song.items() if k != "end"}
    for path, payload in ((base.with_suffix(".mid"), data),
                          (base.with_suffix(".json"), json.dumps(out, indent=1).encode("utf-8"))):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    songs.invalidate()
    return song


def import_file(data: bytes, filename: str, **options) -> dict:
    """Parse, build and save in one step (tools and tests)."""
    parsed = parse(data, filename)
    return save(build_song(parsed, **options), data)
