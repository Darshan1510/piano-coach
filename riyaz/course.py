"""Course: keyboard basics, skill moments, song ladder Levels 1-3 and music terms (PLAN 7.4, 8).

Content is JSON in data/course/ (PLAN 8.5): terms.json, basics.json, skills.json, ladder.json.
State is in the database (riyaz/db.py): course (level floor, basics tasks), skills_done, terms,
song_progress.

Rules:
- Level = the first level (from the level floor) that is not done. A level is done when all its
  songs are done. "Skip to this level" sets the level floor (PLAN 8.3: skip forward, with a warning).
- Song done = song_done(): 100% speed, wait-mode score >= 80, the whole song, the ladder hands.
  Phase 3 has no play-along score (Phase 4); the score is the wait-mode accuracy (DECISIONS.md).
- A skill moment unlocks its term (PLAN 8.2, 7.4). Keyboard basics tasks unlock "middle C" and
  "finger number".
"""

from __future__ import annotations

import copy
import functools
import json
import logging
import re
import time
from pathlib import Path

from . import config, songs
from .db import Store

log = logging.getLogger("riyaz.course")
EPS = 1e-6


class CourseError(ValueError):
    """The text is for the user."""


# ---------------------------------------------------------------------- term marks in texts
#
# A course text names a term only with a mark: [[id]], [[id|shown words]] or
# [[id|shown words|plain words]]. render_text() puts the shown words (the term) for an unlocked
# term, and the plain words for a locked term (PLAN 7.4 Rule 2: a locked term never reaches the
# page). Without plain words, the term's plain word is used (plain_plural for the plural form).
# The page underlines only the marks that it gets (strict: no word search in the text).

TERM_MARK = re.compile(r"\[\[([a-z_]+)(?:\|([^|\]]*))?(?:\|([^|\]]*))?\]\]")


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _plain_for(t: dict, shown: str) -> str:
    plural = shown.lower() == t["plural"].lower() and t["plural"].lower() != t["term"].lower()
    w = t["plain_plural"] if plural else t["plain"]
    return _cap(w) if shown[:1].isupper() else w


def render_text(text: str, unlocked: set[str] | frozenset[str], explained: set[str] | frozenset[str] = frozenset()) -> str:
    """The text for the page. Unlocked term -> [[id|shown]] (the page underlines it). A term that
    this text explains (the lesson that unlocks it) -> the shown words. Locked -> plain words."""
    terms = content()["terms_by_id"]

    def sub(m: re.Match) -> str:
        tid, shown, plain = m.group(1), m.group(2), m.group(3)
        t = terms[tid]
        shown = shown or t["term"]
        if tid in unlocked:
            return f"[[{tid}|{shown}]]"
        if tid in explained:
            return shown
        return plain if plain is not None else _plain_for(t, shown)

    return TERM_MARK.sub(sub, text)


def shown_text(text: str) -> str:
    """The text with every term unlocked and no marks (checks: Rule 6 levels, sentence length)."""
    return TERM_MARK.sub(lambda m: m.group(2) or content()["terms_by_id"][m.group(1)]["term"], text)


def explained_terms(where: str) -> set[str]:
    return {t["id"] for t in content()["terms"] if explains(where, t["id"])}


# ---------------------------------------------------------------------- content


def _read(name: str) -> dict:
    return json.loads((config.course_path() / name).read_text(encoding="utf-8"))


def demo_note_list(demo: dict) -> list[dict]:
    """Demo notes with a start (beats). Without "start", each note starts after the one before
    (plus "after_pause" beats)."""
    out, t = [], 0.0
    for n in demo["notes"]:
        n = dict(n)
        t += float(n.pop("after_pause", 0))
        if "start" not in n:
            n["start"] = t
        t = max(t, float(n["start"]) + float(n.get("dur", 1)))
        out.append(n)
    return sorted(out, key=lambda n: (n["start"], n["pitch"]))


def steps_from_notes(notes: list[dict]) -> list[dict]:
    """One step for each note start: one key ("any") or keys together ("all")."""
    groups: dict[float, list[dict]] = {}
    for n in notes:
        groups.setdefault(round(n["start"], 6), []).append(n)
    steps = []
    for start in sorted(groups):
        g = groups[start]
        if len(g) == 1:
            steps.append({"any": [g[0]["pitch"]], "finger": g[0].get("finger"), "hand": g[0].get("hand")})
        else:
            steps.append({"all": sorted(n["pitch"] for n in g), "fingers": {str(n["pitch"]): n.get("finger") for n in g},
                          "hand": "".join(sorted({n.get("hand", "R") for n in g}, key="RL".index))})
    return steps


@functools.lru_cache(maxsize=1)
def content() -> dict:
    """All course content, checked. Cached (the files are part of the app)."""
    terms = _read("terms.json")["terms"]
    basics = _read("basics.json")
    skills_raw = _read("skills.json")["skills"]
    levels = _read("ladder.json")["levels"]
    term_ids = {t["id"] for t in terms}
    skills = {}
    for s in skills_raw:
        s = copy.deepcopy(s)
        s["demo"]["notes"] = demo_note_list(s["demo"])
        if not s.get("steps"):
            s["steps"] = steps_from_notes(s["demo"]["notes"])
        s.setdefault("tries", config.SKILL_TRIES)
        s["hands"] = sorted({n["hand"] for n in s["demo"]["notes"]}, key="RL".index)
        if s.get("unlocks") is not None and s["unlocks"] not in term_ids:
            raise ValueError(f"skill {s['id']}: unknown term {s['unlocks']}")
        skills[s["id"]] = s
    task_ids = {t["id"] for st in basics["steps"] for t in st["tasks"]}
    for t in terms:
        by = t.get("unlocked_by") or {}
        if "skill" in by and skills.get(by["skill"], {}).get("unlocks") != t["id"]:
            raise ValueError(f"term {t['id']}: skill {by['skill']} does not unlock it")
        if "basics" in by and by["basics"] not in task_ids:
            raise ValueError(f"term {t['id']}: unknown basics task {by['basics']}")
    builtin = songs.load_all()
    for lv in levels:
        for entry in lv["songs"]:
            if entry["song_id"] not in builtin:
                raise ValueError(f"ladder: unknown song {entry['song_id']}")
            for sk in entry["skills"]:
                if sk["id"] not in skills:
                    raise ValueError(f"ladder: unknown skill {sk['id']}")
    known_terms = {t["id"] for t in terms}
    texts = [x for st in basics["steps"] for x in [st["title"], *st["text"], *(t["text"] for t in st["tasks"])]]
    texts += [x for sk in skills.values() for x in [sk["name"], *sk["text"]]]
    texts += [x for lv in levels for x in (lv["title"], lv["text"])] + [t["card"] for t in terms]
    for x in texts:
        for m in TERM_MARK.finditer(x):
            if m.group(1) not in known_terms:
                raise ValueError(f"unknown term mark {m.group(0)} in: {x}")
    demo = songs.validate(basics["demo_song"])
    return {"terms": terms, "terms_by_id": {t["id"]: t for t in terms}, "basics": basics, "skills": skills,
            "levels": levels, "demo_songs": {demo["id"]: demo}}


def demo_song(song_id: str) -> dict | None:
    """Course exercise songs (the 10-note demo of keyboard basics B3). Not in the song list."""
    return content()["demo_songs"].get(song_id)


def get_song(song_id: str) -> dict | None:
    return songs.get(song_id) or demo_song(song_id)


def basics_tasks() -> list[dict]:
    return [t for st in content()["basics"]["steps"] for t in st["tasks"]]


def ladder_entries() -> list[dict]:
    """Every ladder song with its level, in order."""
    out = []
    for lv in content()["levels"]:
        for i, e in enumerate(lv["songs"]):
            out.append({**e, "level": lv["level"], "index": i})
    return out


def ladder_entry(song_id: str) -> dict | None:
    return next((e for e in ladder_entries() if e["song_id"] == song_id), None)


def song_done(run: dict, required_hands) -> bool:
    """PLAN 8.3 "song done": 100% speed and a score of 80 or more.

    Phase 3: the score is the wait-mode accuracy (first-try correct stops, %). Phase 4 replaces
    this with the play-along score (DECISIONS.md, Phase 3b).
    """
    return (run.get("mode") == "wait" and bool(run.get("completed")) and run.get("section") is None
            and float(run.get("speed", 0)) >= config.SONG_DONE_SPEED - EPS
            and set(required_hands) <= set(run.get("hands") or [])
            and float(run.get("accuracy") or 0) >= config.SONG_DONE_SCORE - EPS)


def part_of(song: dict, beat: float) -> int | None:
    for i, s in enumerate(song.get("sections") or []):
        if s["start"] - EPS <= beat < s["end"] - EPS:
            return i
    return None


# ---------------------------------------------------------------------- state


class Course:
    def __init__(self, store: Store, now=time.time):
        self.store = store
        self.now = now

    # ---- level

    def songs_done(self) -> set[str]:
        return {sid for sid, r in self.store.song_progress().items() if r["done"]}

    def level_done(self, level: int, done: set[str] | None = None) -> bool:
        done = self.songs_done() if done is None else done
        lv = next((x for x in content()["levels"] if x["level"] == level), None)
        return lv is not None and all(e["song_id"] in done for e in lv["songs"])

    def level_floor(self) -> int:
        v = self.store.course_get("level_floor", 1)
        return v if isinstance(v, int) and 1 <= v <= config.MAX_COURSE_LEVEL else 1

    def level(self) -> int:
        """The level that the user works on (MAX_COURSE_LEVEL + 1 when all levels are done)."""
        done = self.songs_done()
        for lv in range(self.level_floor(), config.MAX_COURSE_LEVEL + 1):
            if not self.level_done(lv, done):
                return lv
        return config.MAX_COURSE_LEVEL + 1

    def user_level(self) -> int:
        """Level for the difficulty check of imported songs: the skills of this level and below
        count as known. Levels after MAX_COURSE_LEVEL have no lessons yet."""
        return min(self.level(), config.MAX_COURSE_LEVEL)

    # ---- basics

    def basics_tasks_done(self) -> list[str]:
        v = self.store.course_get("basics_tasks", [])
        return v if isinstance(v, list) else []

    def basics_done(self) -> bool:
        done = set(self.basics_tasks_done())
        return all(t["id"] in done for t in basics_tasks())

    def complete_basics_task(self, task_id: str) -> dict:
        if task_id not in {t["id"] for t in basics_tasks()}:
            raise CourseError("The app does not know this step of the keyboard basics.")
        done = self.basics_tasks_done()
        was_done = self.basics_done()
        if task_id not in done:
            self.store.course_set("basics_tasks", done + [task_id])
        unlocked = [t["id"] for t in content()["terms"]
                    if (t.get("unlocked_by") or {}).get("basics") == task_id and self.store.unlock_term(t["id"], self.now())]
        return {"task": task_id, "unlocked": unlocked, "basics_done": self.basics_done(),
                "basics_new": self.basics_done() and not was_done}

    # ---- skill moments

    def skill(self, skill_id: str) -> dict | None:
        return content()["skills"].get(skill_id)

    def skill_public(self, skill_id: str) -> dict | None:
        s = self.skill(skill_id)
        if s is None:
            return None
        term = content()["terms_by_id"].get(s["unlocks"]) if s.get("unlocks") else None
        have = set(self.store.terms())
        where = f"skill {s['id']} text"
        text = [render_text(x, have, explained_terms(where)) for x in s["text"]]
        return {"id": s["id"], "level": s["level"], "name": render_text(s["name"], have, explained_terms(where)),
                "text": text, "demo": s["demo"],
                "steps": s["steps"], "tries": s["tries"], "hands": s["hands"], "unlocks": s.get("unlocks"),
                "unlocks_term": term["term"] if term else None,
                "done": s["id"] in self.store.skills_done()}

    def pending_moments(self, song_id: str) -> list[dict]:
        """Skill moments of a ladder song that the user has not passed (PLAN 8.2)."""
        entry = ladder_entry(song_id)
        if entry is None:
            return []
        done = self.store.skills_done()
        out = []
        for sk in entry["skills"]:
            if sk["id"] in done:
                continue
            skill = self.skill_public(sk["id"])
            out.append({"id": sk["id"], "at_beat": float(sk["at_beat"]), "resume_beat": float(sk["resume_beat"]),
                        "hands": skill["hands"], "skill": skill})
        return sorted(out, key=lambda m: m["at_beat"])

    def complete_skill(self, skill_id: str, session_id: int | None = None) -> dict:
        s = self.skill(skill_id)
        if s is None:
            raise CourseError("The app does not know this new skill.")
        new = self.store.mark_skill(skill_id, session_id, self.now())
        unlocked = []
        if s.get("unlocks") and self.store.unlock_term(s["unlocks"], self.now()):
            unlocked.append(s["unlocks"])
        return {"skill": skill_id, "name": s["name"], "new": new, "unlocked": unlocked}

    # ---- terms (PLAN 7.4)

    def terms_state(self) -> dict:
        """Unlocked terms with their card. A locked term gives only its plain words: the UI never
        shows a locked term (Rule 2)."""
        have = self.store.terms()
        out = []
        for t in content()["terms"]:
            base = {"id": t["id"], "level": t["level"], "plain": t["plain"], "plain_plural": t["plain_plural"]}
            if t["id"] in have:
                base.update(term=t["term"], plural=t["plural"], card=render_text(t["card"], set(have), {t["id"]}),
                            demo=t.get("demo"),
                            pattern=t["pattern"], unlocked=True, seen=bool(have[t["id"]]["seen"]),
                            unlocked_at=have[t["id"]]["unlocked_at"])
            else:
                base.update(unlocked=False, seen=False)
            out.append(base)
        return {"terms": out, "locked_count": sum(1 for t in out if not t["unlocked"])}

    def term_seen(self, term_id: str) -> bool:
        if term_id not in self.store.terms():
            return False
        self.store.term_seen(term_id)
        return True

    # ---- skip forward (PLAN 8.3)

    def skip_info(self, level: int) -> dict:
        """The skills (plain names) that the songs of this level need and that the user has not learned."""
        if not isinstance(level, int) or not 1 <= level <= config.MAX_COURSE_LEVEL:
            raise CourseError("The app does not have this level.")
        done = self.store.skills_done()
        needed = []
        for lv in content()["levels"]:
            if lv["level"] >= level:
                break
            for e in lv["songs"]:
                for sk in e["skills"]:
                    if sk["id"] not in done:
                        needed.append(self.skill(sk["id"])["name"])
        return {"level": level, "needed": needed, "basics": not self.basics_done()}

    def skip_to(self, level: int) -> dict:
        info = self.skip_info(level)
        self.store.course_set("level_floor", level)
        return {**info, "now": self.level()}

    def reset(self) -> None:
        self.store.reset_course()

    # ---- song runs

    def record_run(self, run: dict, session_id: int | None = None, day: str | None = None) -> dict | None:
        """A wait-mode run ended (practice_end). Records the attempt and the song progress."""
        if run.get("mode") != "wait":
            return None
        song = get_song(str(run.get("song_id", "")))
        if song is None:
            return None
        entry = ladder_entry(song["id"])
        required = entry["hands"] if entry else songs.hands_of(song)
        full = run.get("section") is None
        part_errors: dict[int, int] = {}
        for e in run.get("errors") or []:
            p = part_of(song, float(e.get("beat") or 0))
            if p is not None:
                part_errors[p] = part_errors.get(p, 0) + 1
        if full:
            for i in range(len(song.get("sections") or [])):
                part_errors.setdefault(i, 0)
        elif isinstance(run.get("section"), int):
            part_errors.setdefault(run["section"], 0)
        level_before = self.level()
        done = song_done(run, required) if song.get("source") != "course" else False
        accuracy = run.get("accuracy")
        self.store.add_attempt(kind="song", item=song["id"], day=day or today(), t=self.now(), session_id=session_id,
                               hands=run.get("hands"), section=run.get("section"), speed=run.get("speed"),
                               completed=bool(run.get("completed")), stops=run.get("stops"), wrong=run.get("wrong"),
                               accuracy=accuracy, data={"part_errors": part_errors, "seconds": run.get("seconds")})
        before = self.store.song_progress(song["id"]).get(song["id"])
        row = self.store.update_song_progress(song["id"], accuracy=accuracy, full=full and bool(run.get("completed")),
                                              done=done, part_errors=part_errors, t=self.now())
        level_after = self.level()
        return {"song_id": song["id"], "title": song["title"], "ladder": entry is not None,
                "level_of_song": entry["level"] if entry else song.get("level"), "accuracy": accuracy,
                "speed": run.get("speed"), "full": full, "hands": run.get("hands"), "required_hands": required,
                "done": row["done"], "newly_done": row["done"] and not (before or {}).get("done", False),
                "level_before": level_before, "level": level_after,
                "level_up": level_after > level_before, "rule": rule()}

    # ---- the whole state for the UI

    def current_song(self) -> dict | None:
        level = self.level()
        done = self.songs_done()
        for e in ladder_entries():
            if e["level"] == level and e["song_id"] not in done:
                return e
        return None

    def state(self) -> dict:
        have = set(self.store.terms())
        progress = self.store.song_progress()
        done = {sid for sid, r in progress.items() if r["done"]}
        skills_done = self.store.skills_done()
        level = self.level()
        floor = self.level_floor()
        cur = self.current_song()
        all_songs = songs.load_all()
        levels = []
        for lv in content()["levels"]:
            n = lv["level"]
            items = []
            for e in lv["songs"]:
                p = progress.get(e["song_id"], {})
                s = all_songs[e["song_id"]]
                items.append({"song_id": e["song_id"], "title": s["title"], "hands": e["hands"],
                              "seconds": round(s["end"] * 60.0 / s["bpm"]), "done": e["song_id"] in done,
                              "best": p.get("best_full"), "runs": p.get("runs", 0),
                              "current": bool(cur and cur["song_id"] == e["song_id"]),
                              "skills": [{"id": sk["id"], "name": self.skill(sk["id"])["name"],
                                          "done": sk["id"] in skills_done} for sk in e["skills"]]})
            levels.append({"level": n, "title": render_text(lv["title"], have), "text": render_text(lv["text"], have),
                           "done": self.level_done(n, done),
                           "current": n == level, "open": n <= max(level, floor), "songs": items,
                           "done_count": sum(1 for i in items if i["done"])})
        tasks_done = set(self.basics_tasks_done())
        basics = []
        for st in content()["basics"]["steps"]:
            ex = explained_terms(f"basics {st['id']} text")
            basics.append({"id": st["id"], "title": render_text(st["title"], have, ex),
                           "text": [render_text(x, have, ex) for x in st["text"]],
                           "tasks": [{**t, "text": render_text(t["text"], have, explained_terms(f"basics {t['id']}")),
                                      "done": t["id"] in tasks_done} for t in st["tasks"]]})
        return {"level": level, "max_level": config.MAX_COURSE_LEVEL, "all_done": level > config.MAX_COURSE_LEVEL,
                "level_floor": floor, "user_level": self.user_level(),
                "basics": {"done": self.basics_done(), "steps": basics},
                "levels": levels, "current_song": cur["song_id"] if cur else None,
                "skills_done": sorted(skills_done), "rule": rule(),
                "bar_lines": level >= 3}


def rule() -> dict:
    return {"speed": round(config.SONG_DONE_SPEED * 100), "score": config.SONG_DONE_SCORE}


def today() -> str:
    import datetime as _dt

    return _dt.date.today().isoformat()


def course_texts() -> list[tuple[int, str, str]]:
    """(level, where, text) for every course text a user can see (PLAN 7.4 Rule 6 test)."""
    c = content()
    out: list[tuple[int, str, str]] = []
    lvl = c["basics"].get("level", 1)
    for st in c["basics"]["steps"]:
        out.append((lvl, f"basics {st['id']} title", st["title"]))
        out += [(lvl, f"basics {st['id']} text", x) for x in st["text"]]
        out += [(lvl, f"basics {t['id']}", t["text"]) for t in st["tasks"]]
    for s in c["skills"].values():
        out.append((s["level"], f"skill {s['id']} name", s["name"]))
        out += [(s["level"], f"skill {s['id']} text", x) for x in s["text"]]
    for lv in c["levels"]:
        # Level titles and texts are visible before the level starts: they count as Level 1 texts.
        out.append((1, f"level {lv['level']} title", lv["title"]))
        out.append((1, f"level {lv['level']} text", lv["text"]))
    for t in c["terms"]:
        out.append((t["level"], f"term {t['id']} card", t["card"]))
    return out


def explains(text_where: str, term_id: str) -> bool:
    """A text that explains the term: the term's own card, or the skill moment that unlocks it."""
    c = content()
    if text_where.startswith(f"term {term_id} "):
        return True
    by = (c["terms_by_id"].get(term_id) or {}).get("unlocked_by") or {}
    if "basics" in by and text_where == f"basics {by['basics']}":
        return True
    for s in c["skills"].values():
        if s.get("unlocks") == term_id and text_where.startswith(f"skill {s['id']} "):
            return True
    return False


def path_of_content() -> Path:
    return config.course_path()
