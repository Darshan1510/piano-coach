"""Make the MIDI test files in tests/data/midi/ (dev tool; the tests use the files).

  uv run tools/make_test_midi.py

- les-graces-one-track.mid: the Mutopia file les-graces.mid (Public Domain) with both hands
  merged into 1 track and 1 channel (MIDI type 0). Mutopia has no piano file with 1 track.
- synthetic/*.mid: edge cases, made with mido (no copyrighted music: scales and made-up tunes).
"""

from __future__ import annotations

from pathlib import Path

import mido

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "data" / "midi"
SYN = OUT / "synthetic"
TPB = 480


def merge_one_track(src: Path, dst: Path) -> None:
    mid = mido.MidiFile(src)
    events = []
    for track in mid.tracks:
        tick = 0
        for msg in track:
            tick += msg.time
            if msg.type == "end_of_track":
                continue
            if not msg.is_meta and hasattr(msg, "channel"):
                msg = msg.copy(channel=0)
            if msg.is_meta and msg.type == "track_name":
                continue
            events.append((tick, msg))
    events.sort(key=lambda e: (e[0], 0 if e[1].is_meta else 1))
    out = mido.MidiFile(type=0, ticks_per_beat=mid.ticks_per_beat)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage("track_name", name="Les Graces", time=0))
    last = 0
    for tick, msg in events:
        tr.append(msg.copy(time=tick - last))
        last = tick
    tr.append(mido.MetaMessage("end_of_track", time=0))
    out.tracks.append(tr)
    out.save(dst)


def _track(events: list[tuple[int, mido.Message]], name: str | None = None) -> mido.MidiTrack:
    tr = mido.MidiTrack()
    if name:
        tr.append(mido.MetaMessage("track_name", name=name, time=0))
    last = 0
    for tick, msg in sorted(events, key=lambda e: (e[0], 0 if e[1].type == "note_off" or getattr(e[1], "velocity", 1) == 0 else 1)):
        tr.append(msg.copy(time=tick - last))
        last = tick
    tr.append(mido.MetaMessage("end_of_track", time=0))
    return tr


def notes(seq, ch=0, vel0=False, beat=TPB, start=0):
    """seq = [(pitch or [pitches], beats)] -> events."""
    ev = []
    t = start
    for p, beats in seq:
        ps = p if isinstance(p, list) else [p]
        for q in ps:
            if q is None:
                continue
            ev.append((t, mido.Message("note_on", note=q, velocity=80, channel=ch)))
            off = (mido.Message("note_on", note=q, velocity=0, channel=ch) if vel0
                   else mido.Message("note_off", note=q, velocity=64, channel=ch))
            ev.append((t + int(beats * beat * 0.95), off))
        t += int(beats * beat)
    return ev


# A made-up beginner tune (white keys, C position) and a left hand on C and G.
TUNE = [(60, 1), (62, 1), (64, 1), (65, 1), (67, 2), (65, 1), (64, 1), (62, 1), (60, 1), (64, 2), (62, 2), (60, 4)]
BASS = [(48, 4), (43, 4), (48, 4), (48, 4)]


def make_synthetic() -> None:
    SYN.mkdir(parents=True, exist_ok=True)
    meta0 = [(0, mido.MetaMessage("time_signature", numerator=4, denominator=4)),
             (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(90)))]

    # 1. One track, one channel, both hands, note_on velocity 0 as note off (type 0).
    m = mido.MidiFile(type=0, ticks_per_beat=TPB)
    m.tracks.append(_track(meta0 + notes(TUNE, vel0=True) + notes(BASS, vel0=True), "Beginner tune"))
    m.save(SYN / "one-track-vel0.mid")

    # 2. Tempo changes (type 1, tempo map in track 0 only), 2 hands in 2 tracks.
    m = mido.MidiFile(type=1, ticks_per_beat=TPB)
    tempo = [(0, mido.MetaMessage("time_signature", numerator=4, denominator=4)),
             (0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100))),
             (8 * TPB, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(60))),
             (10 * TPB, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100)))]
    m.tracks.append(_track(tempo, "Tempo map"))
    m.tracks.append(_track(notes(TUNE, ch=0), "Right"))
    m.tracks.append(_track(notes(BASS, ch=1), "Left"))
    m.save(SYN / "tempo-changes.mid")

    # 3. Piano + drums (channel 10) + a bass instrument: drums are not a default.
    m = mido.MidiFile(type=1, ticks_per_beat=TPB)
    m.tracks.append(_track(meta0))
    pn = [(0, mido.Message("program_change", program=0, channel=0))] + notes(TUNE, ch=0)
    m.tracks.append(_track(pn, "Piano"))
    dr = notes([(36, 1), (42, 1), (38, 1), (42, 1)] * 5, ch=9)
    m.tracks.append(_track(dr, "Drums"))
    bs = [(0, mido.Message("program_change", program=33, channel=2))] + notes([(36, 4)] * 5, ch=2)
    m.tracks.append(_track(bs, "Bass"))
    m.save(SYN / "drums.mid")

    # 4. Empty tracks, a track with only meta messages, notes outside the 61 keys, a key pressed
    #    again before its note off, a note with no note off.
    m = mido.MidiFile(type=1, ticks_per_beat=TPB)
    m.tracks.append(_track(meta0, "Song with empty tracks"))
    m.tracks.append(_track([], "Empty"))
    m.tracks.append(mido.MidiTrack())
    ev = notes([(60, 1), (64, 1), (67, 1), (100, 1), (24, 1)], ch=0)
    ev += [(5 * TPB, mido.Message("note_on", note=62, velocity=70, channel=0)),
           (6 * TPB, mido.Message("note_on", note=62, velocity=70, channel=0)),  # again, no off between
           (7 * TPB, mido.Message("note_off", note=62, velocity=0, channel=0)),
           (8 * TPB, mido.Message("note_on", note=65, velocity=70, channel=0))]  # never released
    m.tracks.append(_track(ev, "Melody"))
    m.save(SYN / "empty-tracks.mid")

    # 5. Keys together in one hand (left-hand chords C F G C) and a melody, one track.
    m = mido.MidiFile(type=0, ticks_per_beat=TPB)
    chords = [([48, 52, 55], 4), ([48, 53, 57], 4), ([47, 50, 55], 4), ([48, 52, 55], 4)]
    mel = [(72, 2), (71, 2), (69, 2), (72, 2), (74, 2), (71, 2), (72, 4)]
    m.tracks.append(_track(meta0 + notes(chords) + notes(mel), "Keys together"))
    m.save(SYN / "chords-one-track.mid")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    merge_one_track(OUT / "les-graces.mid", OUT / "les-graces-one-track.mid")
    make_synthetic()
    for p in sorted(OUT.rglob("*.mid")):
        print(p.relative_to(ROOT), p.stat().st_size, "bytes")
