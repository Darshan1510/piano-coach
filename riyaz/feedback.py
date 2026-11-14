"""Feedback: live tips, after-run findings and automatic adapt (PLAN 7.1, 7.2, 7.3).

Texts follow PLAN 7.4: a music term is written only as a term mark ([[id|shown|plain]], see
riyaz/course.py render_text), so a locked term never reaches the page. All texts are in
MESSAGES, TIPS and ACTION_LABELS (the Rule 6 test reads all_texts()).

Live tips (LiveTips): at most one at a time, at most one each 4 seconds.
After a run (analyze): the 9 patterns of PLAN 7.2, plus "slips" (wrong neighbor keys, PLAN 6.4;
DECISIONS.md Phase 4), at most 3, most important first. A finding that names a place in the song
has a place {start, end, bar, part} (the page shows a preview and "Show me") and an action.
Adapt (adapt): 3 failed runs -> slower; 3 clean runs -> faster, up to 100%, then the next step.
"""

from __future__ import annotations

import math
import statistics

from . import config

EPS = 1e-6

# ---------------------------------------------------------------------- texts

TIPS = {
    "finger": "Use finger {finger} here.",
    "wait_click": "Wait for [[beat|the beat|the click]].",
    "hold": "Keep the key down longer.",
}

MESSAGES = {
    "hard_spot": "This part is hard for you.",
    "hard_spot_bar": "This part ([[bar|bar {bar}|group of clicks {bar}]]) is hard for you.",
    "in_part": "It is in {part}.",
    "rushing": "You play too early. Wait for [[beat|the beat|the click]].",
    "dragging": "You play too late. Keep up with [[beat|the beat|the click]].",
    "hand_problem_L": "Your left hand needs more practice.",
    "hand_problem_R": "Your right hand needs more practice.",
    "coordination": "Each hand is good. Now play both hands together, slowly.",
    "hand_move": "Move your hand to the new place earlier.",
    "chord_2": "Press both keys together.",
    "chord_n": "Press all {n} keys together.",
    "uneven": "Press all keys with the same force.",
    "short_notes": "Hold the key down until the falling note ends.",
    "slips": "You pressed a key next to the right key {n} times. Look at the finger number before you press.",
}

ACTION_LABELS = {
    "loop_slow": "Practice this part slowly",
    "click": "Play with the click",
    "slower": "Make it slower",
    "hand_only_L": "Left hand only",
    "hand_only_R": "Right hand only",
    "both_half": "Both hands, half speed",
    "move_loop": "Practice the move",
    "keys_loop_2": "Practice these 2 keys",
    "keys_loop_n": "Practice these {n} keys",
}

ADAPT_TEXTS = {
    "slower": "The last 3 runs were hard. The app made the speed slower: {speed}%.",
    "faster": "3 good runs in a row. The app made the speed faster: {speed}%.",
    "loop_faster": "3 good runs in a row. The app made the speed faster: {speed}%.",
    "loop_slower": "The last 3 runs were hard. The app made the speed slower: {speed}%.",
    "next_both": "3 good runs in a row at full speed. Next step: play with both hands.",
    "next_part": "3 good runs in a row at full speed. Next step: {part}.",
    "next_whole": "3 good runs in a row at full speed. Next step: play the whole song.",
    "next_song": "3 good runs in a row at full speed. Next step: a new song.",
    "learned": "You learned this song. The app asks you to play it again in a few days.",
}

# Order = importance (most important first). DECISIONS.md Phase 4.
PRIORITY = ("hard_spot", "coordination", "hand_problem", "rushing", "dragging", "hand_move", "chord",
            "slips", "short_notes", "uneven")


def render(text: str, unlocked) -> str:
    from .course import render_text

    return render_text(text, set(unlocked or ()))


def all_texts() -> list[tuple[int, str, str]]:
    """(level, where, text) of every feedback text. Level 1: they can show at any level."""
    out = [(1, f"tip {k}", v.format(finger=3)) for k, v in TIPS.items()]
    out += [(1, f"finding {k}", v.format(bar=7, part="Part 2", n=3)) for k, v in MESSAGES.items()]
    out += [(1, f"action {k}", v.format(n=3)) for k, v in ACTION_LABELS.items()]
    out += [(1, f"adapt {k}", v.format(speed=85, part="Part 2")) for k, v in ADAPT_TEXTS.items()]
    return out


# ---------------------------------------------------------------------- live tips (PLAN 7.1)


class LiveTips:
    """One tip at a time, at most one each TIP_INTERVAL_S seconds."""

    def __init__(self, interval: float = config.TIP_INTERVAL_S):
        self.interval = interval
        self.last_t = -math.inf
        self.early_run = 0
        self.short_run = 0

    def _emit(self, t: float, tip: str, **kw) -> dict | None:
        if t - self.last_t < self.interval - EPS:
            return None
        self.last_t = t
        return {"tip": tip, "text": TIPS[tip].format(**kw)}

    def on_press(self, res: dict, t: float) -> dict | None:
        if res.get("result") == "hit":
            self.early_run = self.early_run + 1 if res["grade"] == "early" else 0
            if self.early_run >= config.TIP_EARLY_RUN:
                self.early_run = 0
                return self._emit(t, "wait_click")
            return None
        if res.get("result") == "wrong" and res.get("slip") and res.get("finger"):
            # The wrong key is the neighbor of the key that the planned finger plays.
            return self._emit(t, "finger", finger=res["finger"])
        return None

    def on_release(self, res: dict | None, t: float) -> dict | None:
        if not res or not res.get("checked"):
            return None
        self.short_run = self.short_run + 1 if res["short"] else 0
        if self.short_run >= config.TIP_SHORT_RUN:
            self.short_run = 0
            return self._emit(t, "hold")
        return None


# ---------------------------------------------------------------------- after a run (PLAN 7.2)


def beats_per_group(song: dict) -> float:
    return float((song.get("time_signature") or [4, 4])[0])


def bar_of(song: dict, beat: float) -> int:
    """0-based group of clicks (bar) of a beat."""
    return int(math.floor((beat + EPS) / beats_per_group(song)))


def bar_errors(song: dict, log: dict) -> dict[int, int]:
    """Errors per group of clicks: a missed note (also a note with a wrong neighbor key instead)
    counts 1, an extra note that is not a slip counts 1."""
    out: dict[int, int] = {}
    for n in log.get("notes") or []:
        if n["grade"] == "miss":
            b = bar_of(song, n["start"])
            out[b] = out.get(b, 0) + 1
    for e in log.get("extras") or []:
        if e.get("slip_of") is None:
            b = bar_of(song, e["beat"])
            out[b] = out.get(b, 0) + 1
    return out


def error_list(log: dict) -> list[dict]:
    """[{beat, pitch}] of the errors (for the errors per song part, riyaz/course.py)."""
    out = [{"beat": n["start"], "pitch": n["slip"] if n.get("slip") is not None else n["pitch"]}
           for n in log.get("notes") or [] if n["grade"] == "miss"]
    out += [{"beat": e["beat"], "pitch": e["pitch"]} for e in log.get("extras") or [] if e.get("slip_of") is None]
    return sorted(out, key=lambda e: e["beat"])


def hand_accuracy(log: dict) -> dict[str, float]:
    out = {}
    for h in ("R", "L"):
        notes = [n for n in log.get("notes") or [] if n["hand"] == h]
        if notes:
            out[h] = round(100.0 * sum(1 for n in notes if n["grade"] != "miss") / len(notes), 1)
    return out


def key_groups(log: dict) -> list[list[dict]]:
    """Keys together: 2 or more notes of the same hand that start at the same beat."""
    groups: dict[tuple, list[dict]] = {}
    for n in log.get("notes") or []:
        groups.setdefault((n["hand"], round(n["start"], 4)), []).append(n)
    return [g for g in groups.values() if len(g) >= 2]


def groups_full_pct(log: dict) -> float | None:
    gs = key_groups(log)
    if not gs:
        return None
    return round(100.0 * sum(1 for g in gs if all(n["grade"] != "miss" for n in g)) / len(gs), 1)


def section_scores(song: dict, log: dict) -> dict[int, int]:
    """Score (0-100) of each song part in the run log (spaced repetition of song parts)."""
    from .matcher import score_of

    out = {}
    for i, s in enumerate(song.get("sections") or []):
        notes = [n for n in log.get("notes") or [] if s["start"] - EPS <= n["start"] < s["end"] - EPS]
        if not notes:
            continue
        extras = [e for e in log.get("extras") or [] if s["start"] - EPS <= e["beat"] < s["end"] - EPS]
        out[i] = score_of(notes, extras)["total"]
    return out


def run_summary(song: dict, run: dict) -> dict:
    """What the database keeps of a play-along run (riyaz/course.py record_run)."""
    log = run.get("log") or {}
    return {"bar_errors": {str(k): v for k, v in bar_errors(song, log).items()},
            "hand_acc": hand_accuracy(log), "groups_pct": groups_full_pct(log),
            "section_scores": {str(k): v for k, v in section_scores(song, log).items()}}


def _part_name(song: dict, beat: float) -> str | None:
    for s in song.get("sections") or []:
        if s["start"] - EPS <= beat < s["end"] - EPS:
            return s["name"]
    return None


def _place(song: dict, start: float, end: float, rng: tuple[float, float]) -> dict:
    a = max(rng[0], start)
    b = min(rng[1], end)
    if b - a < 1.0:
        b = min(rng[1], a + 1.0)
    return {"start": round(a, 4), "end": round(b, 4), "bar": bar_of(song, a) + 1, "part": _part_name(song, a)}


def analyze(song: dict, run: dict, history: list[dict] | None = None, unlocked=(), vel_range=None,
            alone: dict | None = None) -> dict:
    """Findings of one play-along run.

    history: earlier play-along runs of this song (newest first): {"range": [a, b], "bar_errors": {bar: n}}.
    alone: the newest single-hand score of this song for each hand, {"R": 92, "L": 88}.
    Returns {"findings": the first FINDINGS_MAX, "all": every finding}.
    """
    log = run.get("log") or {}
    notes = log.get("notes") or []
    rng = tuple(run.get("range") or (0.0, song["end"]))
    speed = float(run.get("speed") or 1.0)
    hands = list(run.get("hands") or [])
    score = run.get("score") or {}
    bpg = beats_per_group(song)
    found: dict[str, dict] = {}
    if not notes:
        return {"findings": [], "all": []}

    # Hard spot: >= 2 errors in the same group of clicks in 2 of the last 3 runs that played it.
    this = bar_errors(song, log)
    runs = [{"range": rng, "bar_errors": this}] + [
        {"range": tuple(h.get("range") or (0.0, song["end"])), "bar_errors": {int(k): v for k, v in (h.get("bar_errors") or {}).items()}}
        for h in (history or [])]
    hard = []
    for bar in {b for b in this}:
        a = bar * bpg
        played = [r for r in runs if r["range"][0] - EPS <= max(a, rng[0]) < r["range"][1] - EPS][:config.HARD_SPOT_RUNS[1]]
        bad = sum(1 for r in played if r["bar_errors"].get(bar, 0) >= config.HARD_SPOT_ERRORS)
        if bad >= config.HARD_SPOT_RUNS[0]:
            hard.append((sum(r["bar_errors"].get(bar, 0) for r in played), bar))
    if hard:
        _, bar = max(hard, key=lambda x: (x[0], -x[1]))
        place = _place(song, bar * bpg, (bar + 1) * bpg, rng)
        key = "hard_spot_bar" if "bar" in set(unlocked or ()) else "hard_spot"
        text = MESSAGES[key].format(bar=bar + 1)
        if place["part"]:
            text += " " + MESSAGES["in_part"].format(part=place["part"])
        found["hard_spot"] = {"text": text, "place": place, "data": {"bar": bar + 1, "errors": this.get(bar, 0)},
                              "action": {"id": "loop_slow", "label": ACTION_LABELS["loop_slow"],
                                         "span": [place["start"], place["end"]], "speed": config.LOOP_SLOW_SPEED,
                                         "mode": "play"}}

    # Rushing / dragging: mean timing error of the notes hit.
    errs = [n["err_ms"] for n in notes if n["grade"] != "miss" and n.get("err_ms") is not None]
    if len(errs) >= config.RUSH_MIN_NOTES:
        mean = statistics.fmean(errs)
        if mean < config.RUSH_MS:
            found["rushing"] = {"text": MESSAGES["rushing"], "place": None, "data": {"mean_ms": round(mean, 1), "n": len(errs)},
                                "action": {"id": "click", "label": ACTION_LABELS["click"]}}
        elif mean > config.DRAG_MS:
            found["dragging"] = {"text": MESSAGES["dragging"], "place": None, "data": {"mean_ms": round(mean, 1), "n": len(errs)},
                                 "action": {"id": "slower", "label": ACTION_LABELS["slower"],
                                            "speed": round(max(config.ADAPT_MIN_SPEED, speed - 0.1), 2)}}

    # Hand problem and coordination (both hands played).
    acc = hand_accuracy(log)
    if set(hands) >= {"R", "L"} and len(acc) == 2:
        weak = "L" if acc["L"] < acc["R"] else "R"
        if abs(acc["R"] - acc["L"]) >= config.HAND_GAP - EPS:
            found["hand_problem"] = {"text": MESSAGES[f"hand_problem_{weak}"], "place": None, "data": acc,
                                     "action": {"id": "hand_only", "label": ACTION_LABELS[f"hand_only_{weak}"], "hands": [weak]}}
        alone = alone or {}
        if all((alone.get(h) or 0) >= config.COORD_ALONE - EPS for h in ("R", "L")) \
                and (score.get("total") or 0) < config.COORD_BOTH:
            found["coordination"] = {"text": MESSAGES["coordination"], "place": None, "data": {"alone": alone},
                                     "action": {"id": "both_half", "label": ACTION_LABELS["both_half"],
                                                "hands": ["R", "L"], "speed": 0.5}}

    # Hand move: errors cluster on the notes right after a hand position change.
    moves = sorted({(p["hand"], float(p["start"])) for p in song.get("hand_positions") or []
                    if p["hand"] in hands and p["start"] > rng[0] + EPS and p["start"] < rng[1] - EPS})
    if moves:
        after_ids: dict[int, float] = {}
        for hand, m in moves:
            hn = sorted((n for n in notes if n["hand"] == hand and n["start"] >= m - EPS), key=lambda n: n["start"])
            starts = sorted({n["start"] for n in hn})[:config.MOVE_NOTES]
            for n in hn:
                if n["start"] in starts:
                    after_ids[n["i"]] = m
        bad = lambda n: n["grade"] == "miss" or (n.get("err_ms") or 0) > 1000 * config.PLAY_GOOD_S * 1.5  # noqa: E731
        # (a wrong key or no key, or very late: > 180 ms; the hand came late)
        if "hard_spot" in found:  # the hard spot already names its notes: one finding for one place
            hb = found["hard_spot"]["data"]["bar"] - 1
            after_ids = {i: m for i, m in after_ids.items()
                         if bar_of(song, next(n["start"] for n in notes if n["i"] == i)) != hb}
        after = [n for n in notes if n["i"] in after_ids]
        other = [n for n in notes if n["i"] not in after_ids]
        e_after = sum(1 for n in after if bad(n))
        rate_after = e_after / len(after) if after else 0
        rate_other = sum(1 for n in other if bad(n)) / len(other) if other else 0
        if e_after >= config.MOVE_MIN_ERRORS and rate_after >= 0.5 and rate_after >= 2 * rate_other:
            per: dict[float, int] = {}
            for n in after:
                if bad(n):
                    per[after_ids[n["i"]]] = per.get(after_ids[n["i"]], 0) + 1
            m = max(per, key=lambda k: (per[k], -k))
            place = _place(song, m - 2, m + 2, rng)
            found["hand_move"] = {"text": MESSAGES["hand_move"], "place": place, "data": {"errors": e_after, "move": m},
                                  "action": {"id": "move_loop", "label": ACTION_LABELS["move_loop"],
                                             "span": [place["start"], place["end"]], "speed": config.LOOP_SLOW_SPEED,
                                             "mode": "play"}}

    # Keys together with a missing key (>= 2 times).
    partial = [g for g in key_groups(log) if any(n["grade"] == "miss" for n in g) and any(n["grade"] != "miss" for n in g)]
    if len(partial) >= config.CHORD_MIN_TIMES:
        by_keys: dict[tuple, list] = {}
        for g in partial:
            by_keys.setdefault(tuple(sorted(n["pitch"] for n in g)), []).append(g)
        keys, gs = max(by_keys.items(), key=lambda kv: (len(kv[1]), -kv[1][0][0]["start"]))
        g = gs[0]
        st = g[0]["start"]
        place = _place(song, st - 1, st + max(n["dur"] for n in g) + 0.5, rng)
        n = len(keys)
        found["chord"] = {"text": MESSAGES["chord_2"] if n == 2 else MESSAGES["chord_n"].format(n=n), "place": place,
                          "keys": list(keys), "data": {"times": len(partial)},
                          "action": {"id": "keys_loop", "label": ACTION_LABELS["keys_loop_2"] if n == 2
                                     else ACTION_LABELS["keys_loop_n"].format(n=n),
                                     "span": [place["start"], place["end"]], "keys": list(keys),
                                     "speed": config.LOOP_SLOW_SPEED, "mode": "wait"}}

    # Wrong neighbor keys (likely slips, PLAN 6.4).
    slip_notes = [n for n in notes if n.get("slip") is not None]
    if len(slip_notes) >= config.SLIP_MIN and len(slip_notes) >= config.SLIP_SHARE * len(notes):
        per_bar: dict[int, int] = {}
        for n in slip_notes:
            per_bar[bar_of(song, n["start"])] = per_bar.get(bar_of(song, n["start"]), 0) + 1
        bar = max(per_bar, key=lambda b: (per_bar[b], -b))
        place = _place(song, bar * bpg, (bar + 1) * bpg, rng)
        found["slips"] = {"text": MESSAGES["slips"].format(n=len(slip_notes)), "place": place,
                          "data": {"n": len(slip_notes), "notes": [n["i"] for n in slip_notes]},
                          "action": {"id": "slower", "label": ACTION_LABELS["slower"],
                                     "speed": round(max(config.ADAPT_MIN_SPEED, speed - 0.1), 2)}}

    # Short notes: length score < 60%.
    checked = [n for n in notes if n["grade"] != "miss" and n["dur"] >= config.PLAY_SHORT_MIN_BEATS - EPS]
    if len(checked) >= 3 and (score.get("length") if score.get("length") is not None else 100) < config.SHORT_LENGTH_SCORE:
        found["short_notes"] = {"text": MESSAGES["short_notes"], "place": None, "data": {"length": score.get("length")},
                                "action": None}

    # Uneven touch: velocity SD high where the song has the same force for each note.
    limit = config.UNEVEN_SD
    if vel_range and vel_range[1] > vel_range[0]:
        limit = max(8.0, config.UNEVEN_SD_SHARE * (vel_range[1] - vel_range[0]))
    worst = None
    for hand in ("R", "L"):
        seq = [n for n in sorted(notes, key=lambda n: n["start"]) if n["hand"] == hand]
        run_: list[dict] = []
        for n in seq + [None]:
            if n is not None and n["grade"] != "miss" and n.get("vel") is not None and \
                    (not run_ or n.get("want_vel") == run_[-1].get("want_vel")):
                run_.append(n)
                continue
            if len(run_) >= config.UNEVEN_MIN_NOTES:
                sd = statistics.pstdev([x["vel"] for x in run_])
                if sd > limit and (worst is None or sd > worst[0]):
                    worst = (sd, run_[0]["start"], run_[-1]["start"] + run_[-1]["dur"])
            run_ = [n] if n is not None and n["grade"] != "miss" and n.get("vel") is not None else []
    if worst:
        found["uneven"] = {"text": MESSAGES["uneven"], "place": _place(song, worst[1], worst[2], rng),
                           "data": {"sd": round(worst[0], 1)}, "action": None}

    out = []
    for k in PRIORITY:
        if k in found:
            f = found[k]
            f["id"] = k
            f["text"] = render(f["text"], unlocked)
            out.append(f)
    return {"findings": out[:config.FINDINGS_MAX], "all": out}


# ---------------------------------------------------------------------- automatic adapt (PLAN 7.3)


def _same_speed(a, b) -> bool:
    return abs(float(a) - float(b)) < 0.005


def adapt(runs: list[dict], speed: float, up_big: bool = True, allow_down: bool = True,
          allow_up: bool = True) -> dict | None:
    """runs: the newest play-along results of the same song, hands and part (newest first),
    [{"score": total, "speed": s}]. Only the runs at the current speed count (after a change, the
    count starts again). Returns {"action": "slower" | "faster" | "top", "speed": new} or None."""
    recent = []
    for r in runs:
        if not _same_speed(r.get("speed", 0), speed):
            break
        recent.append(float(r.get("score") or 0))
    if len(recent) < config.ADAPT_RUNS:
        return None
    last = recent[:config.ADAPT_RUNS]
    if allow_down and all(s < config.ADAPT_FAIL for s in last):
        new = max(config.ADAPT_MIN_SPEED, round(speed - config.ADAPT_DOWN, 2))
        return {"action": "slower", "speed": new} if new < speed - EPS else None
    if all(s >= config.ADAPT_CLEAN for s in last):
        if speed >= config.SONG_DONE_SPEED - EPS:
            return {"action": "top", "speed": speed}
        if not allow_up:
            return None
        step = config.ADAPT_UP_BIG if up_big and min(last) >= config.ADAPT_UP_BIG_SCORE else config.ADAPT_UP
        return {"action": "faster", "speed": min(config.SONG_DONE_SPEED, round(speed + step, 2))}
    return None


def next_step(song: dict, hands, section: int | None, span) -> dict:
    """After 3 clean runs at 100%: both hands, the next part, the whole song, or a new song."""
    present = {n["hand"] for n in song["notes"]}
    if set(present) >= {"R", "L"} and set(hands) != {"R", "L"}:
        return {"id": "both", "text": ADAPT_TEXTS["next_both"], "hands": ["R", "L"]}
    secs = song.get("sections") or []
    if isinstance(section, int) and section + 1 < len(secs):
        name = secs[section + 1]["name"]
        return {"id": "part", "text": ADAPT_TEXTS["next_part"].format(part=f"play {name}"), "section": section + 1}
    if section is not None or span is not None:
        return {"id": "whole", "text": ADAPT_TEXTS["next_whole"], "section": None}
    return {"id": "song", "text": ADAPT_TEXTS["next_song"]}


def adapt_text(action: str, speed: float) -> str:
    return ADAPT_TEXTS[action].format(speed=int(round(speed * 100)))
