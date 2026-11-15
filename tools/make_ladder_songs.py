"""Write the built-in songs of course Levels 4-9 (PLAN 8.3) to data/songs/*.json.

The melodies are public-domain tunes (see each "credit" and DECISIONS.md "Phase 5b"). The
arrangements, the left-hand parts and the fingering are written for Riyaz, by hand, in the
tables below. This tool only does the bookkeeping: note starts (each note starts after the one
before in the same hand), note ids, song parts, and the hand positions (PLAN 5.1) from the
hand-written fingers (riyaz.fingering.positions_from_fingers).

  uv run tools/make_ladder_songs.py           # write the 14 song files
  uv run tools/make_ladder_songs.py --check   # only check that the files are up to date

Notation of one hand: a list of (keys, counts, fingers).
- keys: "A4" (C4 = middle C = 60), "Bb4", "F#4", "r" (a pause), or "C3+E3+G3" (keys together).
- counts: length in beats of the song (the time signature unit: a quarter note in 4/4 and
  3/4, an eighth note in 6/8).
- fingers: 1-5, or "5+3+1" for keys together (same order as the keys).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from riyaz import songs  # noqa: E402
from riyaz.fingering import _x, _x_to_pitch  # noqa: E402
from riyaz.handsplit import onsets  # noqa: E402
from riyaz.songs import white_keys_from  # noqa: E402

SONG_DIR = ROOT / "data" / "songs"
NAMES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def pitch(name: str) -> int:
    letter, rest = name[0], name[1:]
    acc = 0
    while rest and rest[0] in "#b":
        acc += 1 if rest[0] == "#" else -1
        rest = rest[1:]
    return 12 * (int(rest) + 1) + NAMES[letter] + acc


def line(*items):
    """A melody line: ("A4", 1, 3), ... Repeated parts are joined with +."""
    return list(items)


# ---------------------------------------------------------------------- left-hand patterns (Level 8)
#
# Triads in root position, low to high: root (finger 5), third (3), fifth (1).

TRIAD = {"": (0, 4, 7), "m": (0, 3, 7)}


def triad(name: str, root_pitch: str) -> list[int]:
    suffix = "m" if name.endswith("m") else ""
    r = pitch(root_pitch)
    return [r + i for i in TRIAD[suffix]]


def block(chords):
    """One block chord for each entry: [(name, root, counts)] -> left-hand items."""
    out = []
    for name, root, n in chords:
        keys = triad(name, root)
        out.append(("+".join(_name(p) for p in keys), n, "5+3+1"))
    return out


def broken(chords):
    """Broken chord in 3/4: root, third, fifth (one key on each beat). PLAN 8.3 Level 8."""
    out = []
    for name, root, _n in chords:
        a, b, c = triad(name, root)
        out += [(_name(a), 1, 5), (_name(b), 1, 3), (_name(c), 1, 1)]
    return out


def dadra(chords):
    """Dadra feel (6 beats, "dha dhi na | dha ti na"): root, then third + fifth together, two times
    in each group of 6 clicks. A chord of 3 counts fills one half."""
    out = []
    for name, root, n in chords:
        a, b, c = triad(name, root)
        upper = (f"{_name(b)}+{_name(c)}", 2, "3+1")
        for _ in range(int(n // 3)):
            out += [(_name(a), 1, 5), upper]
    return out


def keherwa(chords):
    """Keherwa feel (4 beats): root on 1, third + fifth just after 2 (the lift), root on 3,
    third + fifth on 4."""
    out = []
    for name, root, _n in chords:
        a, b, c = triad(name, root)
        up = f"{_name(b)}+{_name(c)}"
        out += [(_name(a), 1.5, 5), (up, 0.5, "3+1"), (_name(a), 1, 5), (up, 1, "3+1")]
    return out


SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


def _name(p: int) -> str:
    return f"{SHARP_NAMES[p % 12]}{p // 12 - 1}"


# ---------------------------------------------------------------------- the songs

JB_CHORUS_A = [("A4", 1, 3), ("A4", 1, 3), ("A4", 2, 3), ("A4", 1, 3), ("A4", 1, 3), ("A4", 2, 3),
               ("A4", 1, 3), ("C5", 1, 5), ("F4", 1.5, 1), ("G4", 0.5, 2), ("A4", 4, 3),
               ("Bb4", 1, 4), ("Bb4", 1, 4), ("Bb4", 1.5, 4), ("Bb4", 0.5, 4),
               ("Bb4", 1, 4), ("A4", 1, 3), ("A4", 1, 3), ("A4", 0.5, 3), ("A4", 0.5, 3)]
JINGLE_BELLS_R = (JB_CHORUS_A + [("A4", 1, 3), ("G4", 1, 2), ("G4", 1, 2), ("A4", 1, 3), ("G4", 2, 2), ("C5", 2, 5)]
                  + JB_CHORUS_A + [("C5", 1, 5), ("C5", 1, 5), ("Bb4", 1, 4), ("G4", 1, 2), ("F4", 4, 1)])
# Left hand (the app plays it by default): one long key in each group of 4 clicks.
LH_F = ("F2", 4, 5)
LH_BB = ("Bb2", 4, 2)
LH_C = ("C3", 4, 1)
LH_G = ("G2", 4, 4)
JINGLE_BELLS_L = [LH_F, LH_F, LH_F, LH_F, LH_BB, LH_F, LH_G, LH_C, LH_F, LH_F, LH_F, LH_F, LH_BB, LH_F, LH_C, LH_F]

SAINTS_R = [("r", 1, None), ("F4", 1, 1), ("A4", 1, 3), ("Bb4", 1, 4), ("C5", 4, 5),
            ("r", 1, None), ("F4", 1, 1), ("A4", 1, 3), ("Bb4", 1, 4), ("C5", 4, 5),
            ("r", 1, None), ("F4", 1, 1), ("A4", 1, 3), ("Bb4", 1, 4), ("C5", 2, 5), ("A4", 2, 3),
            ("F4", 2, 1), ("A4", 2, 3), ("G4", 4, 2),
            ("r", 1, None), ("A4", 1, 3), ("A4", 1, 3), ("G4", 1, 2), ("F4", 3, 1), ("F4", 1, 1),
            ("A4", 2, 3), ("C5", 2, 5), ("C5", 1, 5), ("Bb4", 4, 4),
            ("Bb4", 1, 4), ("A4", 1, 3), ("Bb4", 1, 4), ("C5", 2, 5), ("A4", 2, 3),
            ("F4", 2, 1), ("G4", 2, 2), ("F4", 4, 1)]
SAINTS_L = [LH_F, LH_F, LH_F, LH_F, LH_F, LH_F, LH_F, LH_C, LH_F, LH_F, LH_F, LH_BB, LH_F, LH_F, LH_C, LH_F]

# Yankee Doodle: hand moves (spread hand C E F G A, then F G A Bb C, then C D E F G).
YD_VERSE = [("F4", 1, 3), ("F4", 1, 3), ("G4", 1, 4), ("A4", 1, 5), ("F4", 1, 3), ("A4", 1, 5), ("G4", 1, 4), ("C4", 1, 1),
            ("F4", 1, 3), ("F4", 1, 3), ("G4", 1, 4), ("A4", 1, 5), ("F4", 2, 3), ("E4", 2, 2),
            ("F4", 1, 1), ("F4", 1, 1), ("G4", 1, 2), ("A4", 1, 3), ("Bb4", 1, 4), ("A4", 1, 3), ("G4", 1, 2), ("F4", 1, 1),
            ("E4", 1, 3), ("C4", 1, 1), ("D4", 1, 2), ("E4", 1, 3), ("F4", 2, 4), ("F4", 2, 4)]
YANKEE_DOODLE_R = YD_VERSE + YD_VERSE
YANKEE_DOODLE_L = [LH_F, LH_C, LH_F, ("F2", 2, 5), ("C3", 2, 1), LH_F, LH_BB, LH_C, LH_F] * 2

# Level 5 (3 keys together in the left hand, root position: root 5, third 3, fifth 1).
C3 = ("C", "C3")
G2 = ("G", "G2")
F2 = ("F", "F2")
AM2 = ("Am", "A2")
D3 = ("D", "D3")
DM3 = ("Dm", "D3")
EM3 = ("Em", "E3")
E3 = ("E", "E3")
A2 = ("A", "A2")
BM2 = ("Bm", "B2")
FSM2 = ("F#m", "F#2")


def ch(c, n):
    return (c[0], c[1], n)


HAPPY_BIRTHDAY_R = [("r", 2, None), ("G4", 0.75, 1), ("G4", 0.25, 1),
                    ("A4", 1, 2), ("G4", 1, 1), ("C5", 1, 4), ("B4", 2, 3), ("G4", 0.75, 1), ("G4", 0.25, 1),
                    ("A4", 1, 2), ("G4", 1, 1), ("D5", 1, 5), ("C5", 2, 4), ("G4", 0.75, 1), ("G4", 0.25, 1),
                    ("G5", 1, 5), ("E5", 1, 3), ("C5", 1, 1), ("B4", 1, 2), ("A4", 1, 1), ("F5", 0.75, 5), ("F5", 0.25, 5),
                    ("E5", 1, 3), ("C5", 1, 1), ("D5", 1, 2), ("C5", 3, 1)]
HAPPY_BIRTHDAY_L = [("r", 3, None)] + block([ch(C3, 3), ch(G2, 3), ch(G2, 3), ch(C3, 3), ch(C3, 3), ch(F2, 3),
                                              ch(C3, 2), ch(G2, 1), ch(C3, 3)])

AG_R = [("r", 2, None), ("G4", 1, 1),
        ("C5", 2, 3), ("E5", 0.5, 5), ("C5", 0.5, 3), ("E5", 2, 5), ("D5", 1, 4), ("C5", 2, 3), ("A4", 1, 2),
        ("G4", 2, 1), ("G4", 1, 1), ("C5", 2, 3), ("E5", 0.5, 5), ("C5", 0.5, 3), ("E5", 2, 5), ("D5", 1, 4),
        # Bar 8 "me" (G 2 + "I" E 1), then the second half as in Excell (1900): the Wikipedia
        # "Amazing Grace" LilyPond score (in G, moved here to C).
        ("G5", 2, 5), ("E5", 1, 3),
        ("G5", 1.5, 5), ("E5", 0.5, 3), ("G5", 0.5, 5), ("E5", 0.5, 3), ("C5", 2, 1), ("G4", 1, 1),
        ("A4", 1.5, 2), ("C5", 0.5, 3), ("C5", 0.5, 3), ("A4", 0.5, 2), ("G4", 2, 1), ("G4", 1, 1),
        ("C5", 2, 3), ("E5", 0.5, 5), ("C5", 0.5, 3), ("E5", 2, 5), ("D5", 1, 4),
        ("C5", 3, 3)]
# One chord in each bar after the pickup (14 bars): C C F C C Am G C C F C C G C.
AG_L = [("r", 3, None)] + block([ch(C3, 3), ch(C3, 3), ch(F2, 3), ch(C3, 3), ch(C3, 3), ch(AM2, 3), ch(G2, 3),
                                 ch(C3, 3), ch(C3, 3), ch(F2, 3), ch(C3, 3), ch(C3, 3), ch(G2, 3), ch(C3, 3)])

# Rhythm checked with https://www.flutetunes.com/tunes/oh-my-darling-clementine.mid (in G there):
# dotted eighth + sixteenth (0.75 + 0.25), but even eighths for "C E" (bar 2) and "F E" (bar 3).
CLEMENTINE_R = [("r", 2, None), ("C5", 0.75, 2), ("C5", 0.25, 2),
                ("C5", 1, 2), ("G4", 1, 1), ("E5", 0.75, 4), ("E5", 0.25, 4),
                ("E5", 1, 4), ("C5", 1, 2), ("C5", 0.5, 2), ("E5", 0.5, 4),
                ("G5", 1, 5), ("G5", 1, 5), ("F5", 0.5, 4), ("E5", 0.5, 3),
                ("D5", 2, 2), ("D5", 0.75, 2), ("E5", 0.25, 3),
                ("F5", 1, 4), ("F5", 1, 4), ("E5", 0.75, 3), ("D5", 0.25, 2),
                ("E5", 1, 3), ("C5", 1, 1), ("C5", 0.75, 1), ("E5", 0.25, 3),
                ("D5", 1, 4), ("G4", 1, 1), ("B4", 0.75, 2), ("D5", 0.25, 4),
                ("C5", 3, 3)]
CLEMENTINE_L = [("r", 3, None)] + block([ch(C3, 3), ch(C3, 3), ch(C3, 3), ch(G2, 3), ch(G2, 3), ch(C3, 3),
                                         ch(G2, 3), ch(C3, 3)])

# Level 6: Pachelbel's pattern (D A Bm F#m G D G A), 2 counts each.
CANON_CH = [ch(D3, 2), ch(A2, 2), ch(BM2, 2), ch(FSM2, 2), ch(G2, 2), ch(D3, 2), ch(G2, 2), ch(A2, 2)]
CANON_R = [("F#5", 2, 5), ("E5", 2, 4), ("D5", 2, 3), ("C#5", 2, 2), ("B4", 2, 1), ("A4", 2, 1), ("B4", 2, 2), ("C#5", 2, 3),
           ("D5", 2, 4), ("C#5", 2, 3), ("B4", 2, 2), ("A4", 2, 1), ("G4", 2, 3), ("F#4", 2, 2), ("G4", 2, 3), ("E4", 2, 1),
           ("F#4", 4, 2)]
CANON_L = block(CANON_CH + CANON_CH + [ch(D3, 4)])

POP_R = [("E4", 2, 3), ("G4", 2, 5), ("D4", 2, 2), ("G4", 2, 5), ("C4", 2, 1), ("E4", 2, 3), ("C4", 2, 1), ("F4", 2, 4),
         ("G4", 2, 5), ("E4", 2, 3), ("G4", 2, 5), ("D4", 2, 2), ("E4", 2, 3), ("C4", 2, 1), ("F4", 2, 4), ("C4", 2, 1),
         ("B4", 2, 3), ("D5", 2, 5), ("A4", 2, 2), ("D5", 2, 5), ("G4", 2, 1), ("B4", 2, 3), ("G4", 2, 1), ("C5", 2, 4),
         ("D5", 2, 5), ("B4", 2, 3), ("D5", 2, 5), ("A4", 2, 2), ("B4", 2, 3), ("G4", 2, 1), ("C5", 2, 4), ("G4", 2, 1)]
POP_L = block([ch(C3, 4), ch(G2, 4), ch(AM2, 4), ch(F2, 4)] * 2 + [ch(G2, 4), ch(D3, 4), ch(EM3, 4), ch(C3, 4)] * 2)

# Level 7: Minuet in G (Petzold), first part. Finger 2 goes over the thumb in bar 7.
MINUET_A = [("D5", 1, 5), ("G4", 0.5, 1), ("A4", 0.5, 2), ("B4", 0.5, 3), ("C5", 0.5, 4),
            ("D5", 1, 5), ("G4", 1, 1), ("G4", 1, 1),
            ("E5", 1, 3), ("C5", 0.5, 1), ("D5", 0.5, 2), ("E5", 0.5, 3), ("F#5", 0.5, 4),
            ("G5", 1, 5), ("G4", 1, 1), ("G4", 1, 1),
            ("C5", 1, 4), ("D5", 0.5, 5), ("C5", 0.5, 4), ("B4", 0.5, 3), ("A4", 0.5, 2),
            ("B4", 1, 3), ("C5", 0.5, 4), ("B4", 0.5, 3), ("A4", 0.5, 2), ("G4", 0.5, 1)]
MINUET_R = (MINUET_A + [("F#4", 1, 2), ("G4", 0.5, 1), ("A4", 0.5, 2), ("B4", 0.5, 3), ("G4", 0.5, 1), ("A4", 3, 2)]
            + MINUET_A + [("A4", 1, 3), ("B4", 0.5, 4), ("A4", 0.5, 3), ("G4", 0.5, 2), ("F#4", 0.5, 1), ("G4", 3, 2)])
_G, _C, _D, _A = ("G2", 3, 5), ("C3", 3, 2), ("D3", 3, 1), ("A2", 3, 4)
MINUET_L = [_G, _G, _C, _G, _A, _G, _D, _D, _G, _G, _C, _G, _A, _G, _D, _G]

# Ode to Joy, whole song, both hands. Bars 1-2: the 8-key walk (thumb under at F).
ODE_A = [("E4", 1, 3), ("E4", 1, 3), ("F4", 1, 4), ("G4", 1, 5), ("G4", 1, 5), ("F4", 1, 4), ("E4", 1, 3), ("D4", 1, 2),
         ("C4", 1, 1), ("C4", 1, 1), ("D4", 1, 2), ("E4", 1, 3)]
ODE_FULL_R = ([("C4", 1, 1), ("D4", 1, 2), ("E4", 1, 3), ("F4", 1, 1), ("G4", 1, 2), ("A4", 1, 3), ("B4", 1, 4), ("C5", 1, 5)]
              + ODE_A + [("E4", 1.5, 3), ("D4", 0.5, 2), ("D4", 2, 2)]
              + ODE_A + [("D4", 1.5, 2), ("C4", 0.5, 1), ("C4", 2, 1)]
              + [("D4", 1, 2), ("D4", 1, 2), ("E4", 1, 3), ("C4", 1, 1),
                 ("D4", 1, 2), ("E4", 0.5, 3), ("F4", 0.5, 4), ("E4", 1, 3), ("C4", 1, 1),
                 ("D4", 1, 2), ("E4", 0.5, 3), ("F4", 0.5, 4), ("E4", 1, 3), ("D4", 1, 2),
                 ("C4", 1, 1), ("D4", 1, 2), ("G3", 2, 1)]
              + ODE_A + [("D4", 1.5, 2), ("C4", 0.5, 1), ("C4", 2, 1)])
ODE_FULL_L = ([("C3", 4, 1), ("G2", 4, 4)]
              + block([ch(C3, 4), ch(G2, 4), ch(C3, 4), ch(G2, 4), ch(C3, 4), ch(G2, 4), ch(C3, 4), ch(G2, 2), ch(C3, 2),
                       ch(G2, 4), ch(G2, 2), ch(C3, 2), ch(G2, 4), ch(C3, 2), ch(G2, 2),
                       ch(C3, 4), ch(G2, 4), ch(C3, 4), ch(G2, 2), ch(C3, 2)]))

# Level 8.
SCAR_R = [("D4", 2, 1), ("D4", 1, 1), ("A4", 2, 5), ("A4", 1, 5), ("E4", 1.5, 2), ("F4", 0.5, 3), ("E4", 1, 2), ("D4", 3, 1),
          ("r", 1, None), ("A4", 1, 2), ("C5", 1, 4), ("D5", 2, 5), ("C5", 1, 4), ("A4", 1, 2), ("B4", 1, 3), ("G4", 1, 1),
          ("A4", 2, 2), ("D5", 1, 5),
          ("D5", 2, 5), ("D5", 1, 5), ("C5", 2, 4), ("A4", 1, 2), ("A4", 1, 5), ("G4", 1, 4), ("F4", 1, 3),
          ("E4", 1, 2), ("C4", 2, 1),
          ("D4", 2, 1), ("A4", 1, 5), ("G4", 2, 4), ("F4", 1, 3), ("E4", 1, 2), ("D4", 1, 1), ("C4", 1, 2), ("D4", 3, 1)]
SCAR_CH = [ch(DM3, 3), ch(DM3, 3), ch(C3, 3), ch(DM3, 3), ch(F2, 3), ch(DM3, 3), ch(G2, 3), ch(AM2, 3),
           ch(DM3, 3), ch(AM2, 3), ch(F2, 3), ch(C3, 3), ch(DM3, 3), ch(C3, 3), ch(C3, 3), ch(DM3, 3)]
SCAR_L = broken(SCAR_CH)

# Greensleeves (6/8: one beat = one eighth note). A pickup bar first.
GS_VERSE = [("C5", 2, 2), ("D5", 1, 3), ("E5", 1.5, 4), ("F5", 0.5, 5), ("E5", 1, 4),
            ("D5", 2, 3), ("B4", 1, 2), ("G4", 1.5, 1), ("A4", 0.5, 2), ("B4", 1, 3),
            ("C5", 2, 4), ("A4", 1, 2), ("A4", 1.5, 2), ("G#4", 0.5, 1), ("A4", 1, 2)]
GS_CHORUS = [("G5", 3, 5), ("G5", 1.5, 5), ("F#5", 0.5, 4), ("E5", 1, 3),
             ("D5", 2, 2), ("B4", 1, 1), ("G4", 1.5, 1), ("A4", 0.5, 2), ("B4", 1, 3),
             ("C5", 2, 4), ("A4", 1, 2), ("A4", 1.5, 2), ("G#4", 0.5, 1), ("A4", 1, 2)]
GS_END = [("C5", 1.5, 5), ("B4", 0.5, 4), ("A4", 1, 3), ("G#4", 1.5, 2), ("F#4", 0.5, 1), ("G#4", 1, 2)]
GREENSLEEVES_R = ([("r", 5, None), ("A4", 1, 1)]
                  + GS_VERSE + [("B4", 2, 3), ("G#4", 1, 1), ("E4", 2, 1), ("A4", 1, 1)]
                  + GS_VERSE[:10] + GS_END + [("A4", 6, 3)]
                  + GS_CHORUS + [("B4", 2, 3), ("G#4", 1, 1), ("E4", 3, 1)]
                  + GS_CHORUS[:9] + GS_END + [("A4", 6, 3)])
GS_CH = [ch(AM2, 6), ch(G2, 6), ch(AM2, 6), ch(E3, 6), ch(AM2, 6), ch(G2, 6), ch(AM2, 3), ch(E3, 3), ch(AM2, 6),
         ch(C3, 6), ch(G2, 6), ch(AM2, 6), ch(E3, 6), ch(C3, 6), ch(G2, 6), ch(AM2, 3), ch(E3, 3), ch(AM2, 6)]
GREENSLEEVES_L = [("r", 6, None)] + dadra(GS_CH)

AURA_LINE = [("G4", 1, 1), ("C5", 1, 4), ("B4", 1, 3), ("C5", 1, 4), ("D5", 1, 5), ("A4", 1, 2), ("D5", 2, 5),
             ("C5", 1, 4), ("B4", 1, 3), ("A4", 1, 2), ("B4", 1, 3), ("C5", 4, 4)]
# Verse (the line 2 times), then the refrain (lines 3-4). Checked with
# https://www.flutetunes.com/tunes/aura-lee.mid (in G there, moved here to C).
AURA_REFRAIN = [("E5", 1.5, 3), ("E5", 0.5, 3), ("E5", 2, 3), ("E5", 1.5, 3), ("E5", 0.5, 3), ("E5", 2, 3),
                ("E5", 1, 3), ("D5", 1, 2), ("C5", 1, 1), ("D5", 1, 2), ("E5", 4, 3),
                ("E5", 1, 3), ("E5", 1, 3), ("F5", 1, 4), ("E5", 1, 3),
                ("D5", 1, 4), ("A4", 1, 1), ("D5", 1.5, 4), ("C5", 0.5, 3),
                ("C5", 1, 3), ("B4", 1, 2), ("E5", 1.5, 5), ("D5", 0.5, 4), ("C5", 4, 3)]
AURA_LEE_R = AURA_LINE * 2 + AURA_REFRAIN
# Not only the chords of C: D = D F# A (bars 2, 6, 14) and E = E G# B (bar 10) have a black key.
AURA_LEE_L = keherwa([ch(C3, 4), ch(D3, 4), ch(G2, 4), ch(C3, 4)] * 2
                     + [ch(C3, 4), ch(E3, 4), ch(AM2, 4), ch(C3, 4), ch(C3, 4), ch(D3, 4), ch(G2, 4), ch(C3, 4)])

# Vande Mataram, Tagore's tune (1896, raga Desh), the first part: "Bande mataram ... sujalam
# suphalam malayaja shitalam shasya shyamalam mataram" (lines 1-8 and bars 1-2 of line 9 of the
# akarmatrik notation). Source: Swarabitan vol. 46 (scan https://archive.org/details/in.ernet.dli.2015.356988,
# pages 1-2 of the song), the same notes as the typed copy
# https://www.geetabitan.com/lyrics/rs-b/bande-mataram-bengali-notation.html. Sa = C4, tara Sa = C5,
# komal ni = Bb (Desh: B going up, Bb coming down). One matra = one beat, one line = 4 bars of 4.
# The grace notes (kan: G before Re, G-M and M before Pa, Dha-Ni before tara Sa) are left out.
VM_BANDE = [("C5", 2, 4), ("C5", 4, 4), ("B4", 0.5, 3), ("C5", 0.5, 4), ("D5", 0.5, 5), ("C5", 0.5, 4),  # Ban-de
            ("Bb4", 0.5, 3), ("A4", 0.5, 2), ("G4", 3, 1),
            ("G4", 1, 3), ("A4", 0.5, 4), ("G4", 0.5, 3), ("F4", 0.5, 2), ("G4", 0.5, 3), ("F4", 0.5, 2), ("E4", 0.5, 1)]  # ma-ta-
VM_RAM_END = [("C5", 0.5, 4), ("D5", 0.5, 5), ("C5", 0.5, 4), ("Bb4", 0.5, 3), ("A4", 0.5, 2), ("G4", 0.5, 1),
              ("F4", 1, 2), ("G4", 4, 3)]  # -ram (F with finger 2 over the thumb)
VANDE_MATARAM_R = (VM_BANDE
                   + [("D4", 8, 1), ("F4", 1, 3), ("D4", 1, 1), ("F4", 2, 3),  # -ram, ma-
                      ("E4", 0.5, 2), ("F4", 0.5, 3), ("G4", 1, 4), ("F4", 0.5, 3), ("G4", 0.5, 4), ("A4", 1, 5),
                      ("G4", 0.5, 1), ("A4", 0.5, 2), ("Bb4", 1, 3), ("A4", 0.5, 2), ("Bb4", 0.5, 3), ("C5", 1, 4),
                      ("B4", 0.5, 3), ("C5", 0.5, 4), ("D5", 2, 5), ("C5", 1, 4)]  # -ta-
                   + VM_RAM_END
                   + VM_BANDE
                   + [("D4", 8, 1), ("D4", 1, 1), ("F4", 1, 3), ("F4", 5, 3), ("E4", 1, 2),  # -ram, su-ja-lan
                      ("D4", 1, 3), ("E4", 1, 4), ("D4", 0.5, 3), ("C4", 0.5, 2), ("B3", 1, 1), ("C4", 4, 2),  # su-pha-lan
                      ("D4", 1, 1), ("D4", 1, 1), ("F4", 1, 3), ("F4", 1, 3), ("G4", 3, 4), ("F4", 1, 3),  # ma-la-ya-ja shi-ta-
                      ("G4", 8, 2), ("F4", 2, 1), ("G4", 2, 2), ("B4", 3, 4), ("C5", 1, 5),  # -lam, sha-sya shya-
                      ("C5", 3, 4), ("B4", 1, 3), ("C5", 4, 4), ("C5", 3, 4), ("B4", 1, 3), ("D5", 3, 5), ("C5", 1, 4)]  # -ma-lam ma-ta-
                   + VM_RAM_END)
# Left hand: a drone of Sa and Pa (C and G together), one long sound in each bar, like a tanpura.
VANDE_MATARAM_L = [("C3+G3", 4, "5+1")] * 34

# Level 9 (Phase 6). Fuer Elise (Beethoven, WoO 59), the opening: the pickup, bars 1-7 and the
# first ending. Notes typed from the Mutopia Project LilyPond source (public domain):
# https://www.mutopiaproject.org/ftp/BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59.ly
# ("\\time 3/8", "\\partial 8 e''16 dis'' e'' dis'' e'' b' d'' c'' a'8 r16 c' e' a' b'8 r16 e' gis' b'
# c''8 r16 e' e'' dis'' e'' dis'' e'' b' d'' c'' a'8 r16 c' e' a' b'8 r16 e' c'' b'", ending "a'4";
# left hand "a,16 e a r16 r8", "e,16 e gis r r8"). One click = one eighth note (3/8): a sixteenth = 0.5.
# The last A is held to the end of its group of 3 clicks (the source: a quarter note, then the repeat).
FE_TURN = [("E5", 0.5, 5), ("D#5", 0.5, 4), ("E5", 0.5, 5), ("B4", 0.5, 2), ("D5", 0.5, 4), ("C5", 0.5, 3)]
FUR_ELISE_R = ([("r", 2, None), ("E5", 0.5, 5), ("D#5", 0.5, 4)] + FE_TURN
               + [("A4", 1, 1), ("r", 0.5, None), ("C4", 0.5, 1), ("E4", 0.5, 2), ("A4", 0.5, 4),
                  ("B4", 1, 5), ("r", 0.5, None), ("E4", 0.5, 1), ("G#4", 0.5, 3), ("B4", 0.5, 4),
                  ("C5", 1, 5), ("r", 0.5, None), ("E4", 0.5, 1), ("E5", 0.5, 5), ("D#5", 0.5, 4)]
               + FE_TURN
               + [("A4", 1, 1), ("r", 0.5, None), ("C4", 0.5, 1), ("E4", 0.5, 2), ("A4", 0.5, 4),
                  ("B4", 1, 5), ("r", 0.5, None), ("E4", 0.5, 1), ("C5", 0.5, 4), ("B4", 0.5, 3),
                  ("A4", 3, 2)])
# Left hand: the broken chords (one key after the other, low to high: an arpeggio) of A minor and E major.
FE_AM = [("A2", 0.5, 5), ("E3", 0.5, 2), ("A3", 0.5, 1), ("r", 1.5, None)]
FE_E = [("E2", 0.5, 5), ("E3", 0.5, 2), ("G#3", 0.5, 1), ("r", 1.5, None)]
FUR_ELISE_L = ([("r", 6, None)] + FE_AM + FE_E + FE_AM + [("r", 3, None)] + FE_AM + FE_E
               + [("A2", 0.5, 5), ("E3", 0.5, 2), ("A3", 2, 1)])

# Amazing Grace with smooth chord changes (inversions): the same tune as the Level 5 song (AG_R,
# Excell 1900), the left hand keeps C3 (or moves one key) from chord to chord: C = C E G,
# F/C = C F A, Am/C = C E A, G/B = B D G. The left hand is soft, the tune louder.
_AG_C, _AG_F, _AG_AM, _AG_G = ("C3+E3+G3", 3, "5+3+1"), ("C3+F3+A3", 3, "5+2+1"), ("C3+E3+A3", 3, "5+3+1"), \
    ("B2+D3+G3", 3, "5+3+1")
AG_SMOOTH_L = [("r", 3, None), _AG_C, _AG_C, _AG_F, _AG_C, _AG_C, _AG_AM, _AG_G, _AG_C, _AG_C, _AG_F, _AG_C,
               _AG_C, _AG_G, _AG_C]
AG_SMOOTH_CHORDS = [(3 + 3 * i, 3, nm) for i, nm in enumerate(
    ["C", "C", "F/C", "C", "C", "Am/C", "G/B", "C", "C", "F/C", "C", "C", "G/B", "C"])]

PD = "public domain"
SONGS = [
    dict(id="jingle-bells", title="Jingle Bells", level=4, order=1, bpm=100, ts=(4, 4), key="F major",
         credit=f"Melody by James Lord Pierpont (1857), {PD}. The part that starts 'Jingle bells'. Arrangement and fingering: Riyaz.",
         R=JINGLE_BELLS_R, L=JINGLE_BELLS_L),
    dict(id="when-the-saints", title="When the Saints Go Marching In", level=4, order=2, bpm=100, ts=(4, 4), key="F major",
         credit=f"Traditional American spiritual, {PD}. Arrangement and fingering: Riyaz.",
         R=SAINTS_R, L=SAINTS_L),
    dict(id="yankee-doodle", title="Yankee Doodle", level=4, order=3, bpm=100, ts=(4, 4), key="F major",
         credit=f"Traditional tune (18th century), {PD}. Arrangement and fingering: Riyaz.",
         R=YANKEE_DOODLE_R, L=YANKEE_DOODLE_L),
    dict(id="happy-birthday", title="Happy Birthday to You", level=5, order=1, bpm=100, ts=(3, 4), key="C major",
         credit=f"Melody by Mildred J. Hill and Patty Smith Hill (1893, 'Good Morning to All'), {PD} "
                "(in the US since 2016). Arrangement and fingering: Riyaz.",
         R=HAPPY_BIRTHDAY_R, L=HAPPY_BIRTHDAY_L,
         chords=[(3, 3, "C"), (6, 3, "G"), (9, 3, "G"), (12, 3, "C"), (15, 3, "C"), (18, 3, "F"), (21, 2, "C"),
                 (23, 1, "G"), (24, 3, "C")]),
    dict(id="amazing-grace", title="Amazing Grace", level=5, order=2, bpm=84, ts=(3, 4), key="C major",
         credit=f"Traditional American tune 'New Britain' (1829), words by John Newton (1779), {PD}. "
                "Arrangement and fingering: Riyaz.",
         R=AG_R, L=AG_L),
    dict(id="clementine", title="Oh My Darling, Clementine", level=5, order=3, bpm=100, ts=(3, 4), key="C major",
         credit=f"American folk song (1884, Percy Montrose), {PD}. Arrangement and fingering: Riyaz.",
         R=CLEMENTINE_R, L=CLEMENTINE_L),
    dict(id="canon-in-d", title="Canon in D (easy pattern)", level=6, order=1, bpm=72, ts=(4, 4), key="D major",
         credit=f"Johann Pachelbel (about 1680), {PD}. The left-hand pattern and 2 simple top lines. "
                "Arrangement and fingering: Riyaz.",
         R=CANON_R, L=CANON_L, parts=[(0, 16), (16, 36)]),
    dict(id="pop-loop", title="Pop loop: C, G, Am, F", level=6, order=2, bpm=90, ts=(4, 4), key="C major",
         credit=f"Written for Riyaz: the 4-step loop of many pop songs (C, G, Am, F), then the same loop "
                f"from G (G, D, Em, C). No older song; {PD} (free to use).",
         R=POP_R, L=POP_L),
    dict(id="minuet-in-g", title="Minuet in G (first part)", level=7, order=1, bpm=96, ts=(3, 4), key="G major",
         credit=f"Christian Petzold (1725, BWV Anh. 114, from the Notebook for Anna Magdalena Bach), {PD}. "
                "Left hand and fingering: Riyaz.",
         R=MINUET_R, L=MINUET_L),
    dict(id="ode-to-joy-full", title="Ode to Joy (whole song, both hands)", level=7, order=2, bpm=100, ts=(4, 4),
         key="C major",
         credit=f"Melody by Ludwig van Beethoven (1824), {PD}. Bars 1-2 (the 8-key walk), left hand and "
                "fingering: Riyaz.",
         R=ODE_FULL_R, L=ODE_FULL_L, parts=[(0, 8), (8, 24), (24, 40), (40, 56), (56, 72)]),
    dict(id="scarborough-fair", title="Scarborough Fair", level=8, order=1, bpm=100, ts=(3, 4), key="D minor",
         credit=f"Traditional English tune (Anderson/MacColl collection), {PD} (the old folk tune, not a later "
                "recorded arrangement). "
                "Left hand and fingering: Riyaz.",
         R=SCAR_R, L=SCAR_L),
    dict(id="greensleeves", title="Greensleeves", level=8, order=2, bpm=150, ts=(6, 8), key="A minor",
         credit=f"Traditional English tune (16th century), {PD}. Left hand (6-click feel) and fingering: Riyaz.",
         R=GREENSLEEVES_R, L=GREENSLEEVES_L, parts=[(0, 30), (30, 54), (54, 78), (78, 102)]),
    dict(id="aura-lee", title="Aura Lee", level=8, order=3, bpm=90, ts=(4, 4), key="C major",
         credit=f"George R. Poulton and W. W. Fosdick (1861), {PD}. Left hand (4-click feel) and fingering: Riyaz.",
         R=AURA_LEE_R, L=AURA_LEE_L),
    dict(id="vande-mataram", title="Vande Mataram (Tagore tune, first part)", level=8, order=4, bpm=72, ts=(4, 4),
         key="C major",
         credit=f"Tune by Rabindranath Tagore (1896, raga Desh), words by Bankim Chandra Chattopadhyay (1875), {PD}. "
                "Notes from Swarabitan vol. 46 (Sa = C); grace notes left out. Check by ear. "
                "Left hand (a drone of C and G) and fingering: Riyaz.",
         R=VANDE_MATARAM_R, L=VANDE_MATARAM_L),
    dict(id="fur-elise", title="Für Elise (opening)", level=9, order=1, bpm=96, ts=(3, 8), key="A minor",
         credit=f"Ludwig van Beethoven (1810, WoO 59), {PD}. Notes from the Mutopia Project edition; "
                "the opening only. Fingering: Riyaz.",
         R=FUR_ELISE_R, L=FUR_ELISE_L, vel=(56, 44), parts=[(0, 15), (15, 27)],
         chords=[(6, 3, "Am"), (9, 3, "E"), (12, 3, "Am"), (18, 3, "Am"), (21, 3, "E"), (24, 3, "Am")]),
    dict(id="amazing-grace-smooth", title="Amazing Grace (smooth chords)", level=9, order=2, bpm=84, ts=(3, 4),
         key="C major",
         credit=f"Traditional American tune 'New Britain' (1829), words by John Newton (1779), {PD}. "
                "Left hand with smooth chord changes and fingering: Riyaz.",
         R=AG_R, L=AG_SMOOTH_L, vel=(86, 50), chords=AG_SMOOTH_CHORDS),
]


def hand_notes(items, hand: str, vel: int) -> list[dict]:
    out, t = [], 0.0
    for keys, n, fingers in items:
        if keys != "r":
            ps = [pitch(k) for k in keys.split("+")]
            fs = [int(f) for f in str(fingers).split("+")]
            assert len(ps) == len(fs), (keys, fingers)
            for p, f in zip(ps, fs):
                out.append({"pitch": p, "start": round(t, 4), "dur": float(n), "hand": hand, "finger": f, "vel": vel})
        t += n
    return out, t


MAX_SPAN = 10  # semitones: the look-ahead does not make a hand wider than this (C to A = 9)


def _fits(want: dict[int, int]) -> bool:
    """Fingers 1-5 on keys that go away from the thumb, with room for the fingers between."""
    fs = sorted(want)
    # A thumb can reach one key more (a spread hand: G C D E F).
    return all(fb - fa <= want[fb] - want[fa] <= 2 * (fb - fa) + 2 + (fa == 1) for fa, fb in zip(fs, fs[1:]))


def _black_x(x: int, hand: str) -> bool:
    return (_x_to_pitch(x, hand) % 12) in (1, 3, 6, 8, 10)


def frame_from(want: dict[int, int], hand: str) -> list[int]:
    """Keys (mirrored x) of fingers 1-5: the known fingers, and natural keys for the others.
    Between 2 known fingers: the white key nearest to the even spread (a black key only when
    there is no white key). Past the
    ends: the next key, a white key when there is one 1 or 2 keys away."""
    frame: list[int | None] = [want.get(f) for f in range(1, 6)]
    known = [i for i in range(5) if frame[i] is not None]
    for i in range(5):
        if frame[i] is not None:
            continue
        lo = max((j for j in known if j < i), default=None)
        hi = min((j for j in known if j > i), default=None)
        if lo is not None and hi is not None:
            lo_x = max(frame[j] for j in range(lo, i) if frame[j] is not None)
            room = range(lo_x + 1, frame[hi] - (hi - i) + 1)
            target = frame[lo] + (frame[hi] - frame[lo]) * (i - lo) / (hi - lo)
            frame[i] = min(room, key=lambda x: (_black_x(x, hand), abs(x - target)))
    for i in range(5):  # past the last known finger (away from the thumb)
        if frame[i] is None and i > 0 and frame[i - 1] is not None:
            a, b = frame[i - 1] + 1, frame[i - 1] + 2
            frame[i] = b if _black_x(a, hand) or not _black_x(b, hand) and _black_x(frame[i - 1], hand) else a
    for i in range(4, -1, -1):  # before the first known finger (toward the thumb)
        if frame[i] is None:
            a, b = frame[i + 1] - 1, frame[i + 1] - 2
            frame[i] = b if _black_x(a, hand) or not _black_x(b, hand) and _black_x(frame[i + 1], hand) else a
    return [int(x) for x in frame]  # type: ignore[arg-type]


def hand_positions(notes: list[dict], hand: str) -> list[dict]:
    """Hand positions (PLAN 5.1) from the hand-written fingers. A new position starts when a finger
    is not on its key. The new position looks ahead: it takes the keys of the next notes too,
    until a finger needs a different key (then the hand moves again)."""
    groups = onsets(notes)
    maps = [{n["finger"]: _x(n["pitch"], hand) for n in g} for g in groups]
    out: list[dict] = []
    frame: list[int] | None = None
    for i, g in enumerate(groups):
        if frame is not None and all(frame[f - 1] == x for f, x in maps[i].items()):
            continue
        want: dict[int, int] = {}
        for m in maps[i:]:
            merged = dict(want)
            ok = True
            for f, x in m.items():
                if merged.get(f, x) != x or (x in merged.values() and merged.get(f) != x):
                    ok = False
                merged[f] = x
            if not ok or not _fits(merged) or (want and max(merged.values()) - min(merged.values()) > MAX_SPAN):
                break
            want = merged
        if not want:
            want = maps[i]
        frame = frame_from(want, hand)
        keys = [_x_to_pitch(x, hand) for x in frame]
        pos = {"hand": hand, "start": g[0]["start"], "thumb_pitch": keys[0]}
        if keys != white_keys_from(keys[0], hand):
            pos["keys"] = keys
        out.append(pos)
    return out


def build(spec: dict) -> dict:
    vel_r, vel_l = spec.get("vel", (80, 62))  # Level 9: soft songs, the tune louder than the left hand
    right, r_end = hand_notes(spec["R"], "R", vel_r)
    left, l_end = hand_notes(spec.get("L") or [], "L", vel_l)
    num = spec["ts"][0]
    end = max(r_end, l_end)
    assert abs(r_end - end) < 1e-6 or not right, (spec["id"], r_end, l_end)
    assert abs(end / num - round(end / num)) < 1e-6, (spec["id"], "end is not a whole group", end)
    notes = sorted(right + left, key=lambda n: (n["start"], n["hand"] != "L", n["pitch"]))
    for i, n in enumerate(notes):
        n["id"] = i
    positions = hand_positions([n for n in notes if n["hand"] == "R"], "R")
    positions += hand_positions([n for n in notes if n["hand"] == "L"], "L")
    bar = float(num)
    parts = spec.get("parts")
    if parts is None:
        group = 4 * bar
        edges = [i * group for i in range(int(end // group) + 1)]
        if edges[-1] < end - 1e-6:
            edges.append(end)
        if len(edges) > 2 and edges[-1] - edges[-2] < 2 * bar - 1e-6:  # a short last part joins the one before
            edges.pop(-2)
        parts = list(zip(edges, edges[1:]))
    song = {
        "id": spec["id"], "title": spec["title"], "source": "builtin", "bpm": spec["bpm"],
        "time_signature": list(spec["ts"]), "key": spec["key"], "level": spec["level"], "order": spec["order"],
        "credit": spec["credit"],
        "sections": [{"name": f"Part {i + 1}", "start": a, "end": b} for i, (a, b) in enumerate(parts)],
        "hand_positions": sorted(positions, key=lambda p: (p["hand"] != "R", p["start"])),
        "notes": notes,
    }
    if spec.get("chords"):
        song["chords"] = [{"start": a, "dur": d, "name": nm} for a, d, nm in spec["chords"]]
    songs.validate(song)
    return song


def dump(song: dict) -> str:
    """Same layout as the hand-written Level 1-3 files: one note per line."""
    lines = ["{"]
    keys = [k for k in song if k not in ("notes", "sections", "hand_positions", "chords")]
    for k in keys:
        lines.append(f" {json.dumps(k)}: {json.dumps(song[k], ensure_ascii=False)},")
    for k in ("sections", "hand_positions", "chords"):
        if k in song:
            lines.append(f" {json.dumps(k)}: [")
            lines.append(",\n".join(f"  {json.dumps(x, ensure_ascii=False)}" for x in song[k]))
            lines.append(" ],")
    lines.append(' "notes": [')
    lines.append(",\n".join(f"  {json.dumps(n)}" for n in song["notes"]))
    lines.append(" ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="exit 1 if a file is not up to date")
    args = ap.parse_args()
    stale = []
    for spec in SONGS:
        text = dump(build(spec))
        path = SONG_DIR / f"{spec['id']}.json"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
            continue
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({len(json.loads(text)['notes'])} notes)")
    if stale:
        print("not up to date:", ", ".join(stale))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
