"""Write a generated test song (test data only, not a real song) for renderer checks.

  uv run tools/make_test_song.py                       # 200 notes -> .cache/test-songs/test-200-notes.json
  uv run tools/make_test_song.py --notes 400 --out /some/folder
  RIYAZ_EXTRA_SONG_DIR=.cache/test-songs uv run main.py   # the song is then in the Songs list

Both hands, with keys together, finger numbers and hand position changes, so that the
renderer draws everything that a real song has.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHITE = [0, 2, 4, 5, 7, 9, 11]


def white_keys(thumb: int, step: int) -> list[int]:
    keys, p = [thumb], thumb
    while len(keys) < 5:
        p += step
        if p % 12 in WHITE:
            keys.append(p)
    return keys


def make(count: int = 200, bpm: int = 120) -> dict:
    notes: list[dict] = []
    positions = []
    r_thumbs = [60, 62, 64, 65, 67]  # right hand moves up and down
    l_thumbs = [48, 50, 52, 53]
    beat = 0.0
    group = 0
    while len(notes) < count:
        rt = r_thumbs[group % len(r_thumbs)]
        lt = l_thumbs[group % len(l_thumbs)]
        positions.append({"hand": "R", "start": beat, "thumb_pitch": rt})
        positions.append({"hand": "L", "start": beat, "thumb_pitch": lt})
        rk, lk = white_keys(rt, 1), white_keys(lt, -1)
        for i in range(8):  # 8 half-beat right-hand notes per group
            if len(notes) >= count:
                break
            f = [1, 2, 3, 4, 5, 4, 3, 2][i]
            notes.append({"pitch": rk[f - 1], "start": beat + i * 0.5, "dur": 0.5, "hand": "R", "finger": f, "vel": 80})
        for i, fs in enumerate(([5, 3, 1], [5, 1])):  # left hand: 3 keys, then 2 keys together
            for f in fs:
                if len(notes) >= count:
                    break
                notes.append({"pitch": lk[f - 1], "start": beat + i * 2, "dur": 2.0, "hand": "L", "finger": f,
                              "vel": 64})
        beat += 4
        group += 1
    for i, n in enumerate(notes):
        n["id"] = i
    end = max(n["start"] + n["dur"] for n in notes)
    sections = [{"name": f"Part {i + 1}", "start": float(a), "end": float(min(a + 16, end))}
                for i, a in enumerate(range(0, int(end), 16))]
    return {"id": f"test-{count}-notes", "title": f"Test song ({count} notes)", "source": "builtin", "bpm": bpm,
            "time_signature": [4, 4], "key": "C major", "level": 2, "order": 99,
            "credit": "Generated test data (not a real song).", "notes": notes, "chords": [],
            "sections": sections, "hand_positions": positions}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--notes", type=int, default=200)
    ap.add_argument("--bpm", type=int, default=120)
    ap.add_argument("--out", default=str(ROOT / ".cache" / "test-songs"))
    args = ap.parse_args()
    song = make(args.notes, args.bpm)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{song['id']}.json"
    path.write_text(json.dumps(song, indent=1))
    print(f"{path} ({len(song['notes'])} notes, {song['notes'][-1]['start'] + 2:.0f} beats)")


if __name__ == "__main__":
    main()
