"""Fingering test (PLAN 5.3): automatic fingering vs the hand-written fingering of the built-in songs.

  uv run tools/fingering_report.py

Prints the match for each song and for all notes, in beginner mode (Levels 1-3, the mode that
the app uses for these songs) and in normal mode (the mode for songs with black keys and for
Levels 4+). Normal mode also runs on a small set of passages with black keys and standard
textbook fingering (``tests/data/fingering/*.json``).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from riyaz import fingering, songs  # noqa: E402

BLACK_KEY_SET = Path(__file__).resolve().parent.parent / "tests" / "data" / "fingering"


def black_key_set() -> list[dict]:
    """Short passages with black keys and hand-written textbook fingering (normal-mode test)."""
    return [json.loads(p.read_text()) for p in sorted(BLACK_KEY_SET.glob("*.json"))]


def report(beginner: bool = True, extra: bool = False) -> dict:
    """extra=True scores the black-key set instead of the built-in songs."""
    rows = {}
    if extra:
        pool = black_key_set()
    else:
        pool = [s for s in sorted(songs.load_all().values(), key=lambda s: (s["level"], s["order"]))
                if s["source"] == "builtin"]
    for song in pool:
        notes = copy.deepcopy(song["notes"])
        written = {n["id"]: n["finger"] for n in notes}
        for n in notes:
            n["finger"] = None
        fingering.finger_song(notes, beginner=beginner)
        same = sum(1 for n in notes if n["finger"] == written[n["id"]])
        rows[song["id"]] = (same, len(notes))
    same = sum(a for a, _ in rows.values())
    total = sum(b for _, b in rows.values())
    return {"songs": rows, "same": same, "total": total, "ratio": same / total if total else 0.0}


def _print(title: str, r: dict) -> None:
    print(title)
    for sid, (a, b) in r["songs"].items():
        print(f"  {sid:26s} {a:3d}/{b:3d} = {a / b:6.1%}")
    print(f"  {'all':26s} {r['same']:3d}/{r['total']:3d} = {r['ratio']:6.1%}\n")


def main() -> None:
    for beginner in (True, False):
        mode = "Beginner mode (Levels 1-3)" if beginner else "Normal mode"
        _print(f"{mode}, built-in songs", report(beginner))
        _print(f"{mode}, black-key set", report(beginner, extra=True))
    a, b = report(False), report(False, extra=True)
    same, total = a["same"] + b["same"], a["total"] + b["total"]
    print(f"Normal mode, built-in songs + black-key set: {same}/{total} = {same / total:.1%}")


if __name__ == "__main__":
    main()
