"""Weekly coach (PLAN 3 "Advanced", 12 Phase 6): a weekly summary and plain tips.

Two sources:

1. **Rule summary** (always there, no download): plain sentences from the progress data of the
   last 7 days (practice days and minutes, streak, songs and scores, songs done, the strongest
   and the weakest skill) and up to 3 tips from simple rules (the weakest skill, few practice
   days, a left hand that is too loud).
2. **Local LLM coach** (optional, off by default, a Settings switch): the Ollama HTTP API on
   this Mac only (http://127.0.0.1:11434, ``/api/tags`` and ``/api/generate``). The app sends
   only the progress JSON of ``week_data`` (numbers, song titles, skill names): no audio, no
   names, no files. Short timeouts. When Ollama is not running (or has no model), the page says
   "The coach is not running." and shows the rule summary. The app never starts or installs
   Ollama and never downloads a model.

The host is fixed (127.0.0.1); only the port can change (RIYAZ_OLLAMA_PORT, for tests with a fake
server). Texts follow PLAN 7.4: term marks for music terms; the LLM text gets the plain word for
each locked term.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

from . import session as session_mod, skills as skills_mod
from .db import Store

log = logging.getLogger("riyaz.coach")

HOST = "127.0.0.1"
DEFAULT_PORT = 11434
DEFAULT_MODEL = "llama3.2:3b"
STATUS_TIMEOUT_S = 1.5
GENERATE_TIMEOUT_S = 20.0
MAX_REPLY = 1_000_000  # bytes
MAX_TEXT = 1500
SETTINGS_KEY = "coach"
NOT_RUNNING = "The coach is not running. Start Ollama on this Mac, or use the summary below."
NO_MODEL = "The coach has no model {model}. Download it in Ollama, or select a different model."

WEEK_DAYS = 7


class CoachUnavailable(RuntimeError):
    """Ollama is not running, has no model, or did not answer in time. The text is for the user."""


# ---------------------------------------------------------------------- settings


def settings(store: Store) -> dict:
    v = store.get(SETTINGS_KEY, None)
    v = v if isinstance(v, dict) else {}
    model = v.get("model") if isinstance(v.get("model"), str) and v.get("model") else DEFAULT_MODEL
    return {"enabled": v.get("enabled") is True, "model": model[:80]}


_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")


def set_settings(store: Store, body: dict) -> dict:
    cur = settings(store)
    if isinstance(body.get("enabled"), bool):
        cur["enabled"] = body["enabled"]
    m = body.get("model")
    if isinstance(m, str) and _MODEL_RE.match(m.strip()):
        cur["model"] = m.strip()
    store.set(SETTINGS_KEY, cur)
    return cur


# ---------------------------------------------------------------------- the progress data (JSON only)


def week_data(store: Store, course=None, today: str | None = None) -> dict:
    """The progress of the last 7 days. Numbers, song titles and skill names only."""
    from . import course as course_mod

    today = today or course_mod.today()
    end = dt.date.fromisoformat(today)
    first = (end - dt.timedelta(days=WEEK_DAYS - 1)).isoformat()
    days = store.days(first, today)
    per_day = []
    for i in range(WEEK_DAYS):
        d = (end - dt.timedelta(days=WEEK_DAYS - 1 - i)).isoformat()
        v = days.get(d, {"seconds": 0, "sessions": 0})
        per_day.append({"day": d, "minutes": round(v["seconds"] / 60.0, 1), "sessions": v["sessions"]})
    practiced = session_mod.practice_days(days)
    streak = session_mod.streak(store.all_days(), today)
    songs: dict[str, dict] = {}
    dyn_low = 0
    for a in store.attempts(kind="song", limit=2000):
        if a["day"] < first or a["day"] > today or not a["completed"]:
            continue
        d = a["data"] or {}
        if d.get("loop_pass"):
            continue
        song = course_mod.get_song(a["item"])
        if song is None or song.get("source") == "course":
            continue
        s = songs.setdefault(a["item"], {"title": song["title"], "runs": 0, "best_score": None, "best_wait": None})
        s["runs"] += 1
        if d.get("mode") == "play" and isinstance(d.get("score"), dict):
            v = d["score"].get("total")
            if isinstance(v, (int, float)):
                s["best_score"] = v if s["best_score"] is None else max(s["best_score"], v)
            dyn = d.get("dynamics")
            if isinstance(dyn, dict) and isinstance(dyn.get("balance"), dict) and not dyn["balance"].get("ok"):
                dyn_low += 1
        elif a["accuracy"] is not None:
            s["best_wait"] = a["accuracy"] if s["best_wait"] is None else max(s["best_wait"], a["accuracy"])
    t0 = dt.datetime.combine(dt.date.fromisoformat(first), dt.time()).timestamp()
    done = [course_mod.get_song(sid.split("#")[0]) for sid, r in store.song_progress().items()
            if r["done"] and (r.get("done_at") or 0) >= t0]
    games = [a for a in store.attempts(kind="intuition", limit=500) if first <= a["day"] <= today]
    unlocked = set(store.terms())
    model = [s for s in skills_mod.model(store, unlocked) if s["value"] is not None]
    from .course import plain_text

    return {
        "today": today, "days": per_day, "practice_days": sum(1 for x in per_day if x["day"] in practiced),
        "minutes": round(sum(x["minutes"] for x in per_day), 1), "sessions": sum(x["sessions"] for x in per_day),
        "streak": streak["days"],
        "level": course.level() if course is not None else None,
        "songs": sorted(songs.values(), key=lambda s: -(s["runs"])),
        "songs_done": sorted({s["title"] for s in done if s}),
        "ear_games": len(games),
        "ear_score": round(sum(a["accuracy"] or 0 for a in games) / len(games), 1) if games else None,
        "skills": [{"id": s["id"], "name": plain_text(s["name"], unlocked), "value": s["value"]} for s in model],
        "left_too_loud": dyn_low,
    }


# ---------------------------------------------------------------------- the rule summary

TIPS = {
    "days": "Practice a little each day. 10 minutes each day is better than one long practice.",
    "start": "Open Today and do the 4 steps. The app picks your song.",
    "keys": "Use Play mode first. The song waits for the right key.",
    "rhythm": "Turn on the click and play slowly. Then make the speed higher in small steps.",
    "right": "Practice the right hand alone first. Then play both hands.",
    "left": "Practice the left hand alone first. Then play both hands.",
    "coordination": "Play both hands at a low speed. Then make the speed higher in small steps.",
    "chords": "Play the [[chord|chord|keys together]] ear games. Look at your hand before you press.",
    "scales": "Play the Jam game. Use only the keys that glow.",
    "ear": "Play one ear game each day. Sing the tune, then find it on the keys.",
    "loud_left": "Play the tune louder than the left hand. Press the left-hand keys more gently.",
}


def _title(text) -> str:
    """A song title in a rule text: no term marks (a title "[[x]]" is not a mark, PLAN 7.4)."""
    return str(text).replace("[[", "[ [").replace("]]", "] ]")


def rule_summary(data: dict, unlocked=()) -> dict:
    """Plain sentences and up to 3 tips from week_data. Texts with term marks (PLAN 7.4)."""
    from .course import render_text

    lines: list[str] = []
    tips: list[str] = []
    n, mins = data["practice_days"], data["minutes"]
    if n == 0:
        lines.append("You did not practice in the last 7 days.")
        tips.append(TIPS["start"])
    else:
        lines.append(f"You practiced on {n} of the last 7 days, {int(round(mins))} minutes in all.")
    if data["streak"] > 1:
        lines.append(f"You practiced {data['streak']} days in a row. Keep it up.")
    played = data["songs"]
    if played:
        best = max(played, key=lambda s: s["best_score"] if s["best_score"] is not None else -1)
        if best["best_score"] is not None:
            lines.append(f"You played {len(played)} song{'s' if len(played) != 1 else ''}. "
                         f"Your best score is {int(best['best_score'])} in \"{_title(best['title'])}\".")
        else:
            lines.append(f"You played {len(played)} song{'s' if len(played) != 1 else ''} in Play mode.")
    if data["songs_done"]:
        lines.append("Done this week: " + ", ".join(f"\"{_title(t)}\"" for t in data["songs_done"][:4]) + ".")
    if data["ear_games"]:
        lines.append(f"You played {data['ear_games']} ear game{'s' if data['ear_games'] != 1 else ''}.")
    skills = data["skills"]
    if len(skills) >= 2:
        hi = max(skills, key=lambda s: s["value"])
        lo = min(skills, key=lambda s: s["value"])
    if len(skills) >= 2 and hi["value"] > lo["value"]:
        lines.append(f"Your strongest skill is \"{hi['name']}\". Your weakest skill is \"{lo['name']}\".")
        if lo["id"] in TIPS:
            tips.append(TIPS[lo["id"]])
    if 0 < n < 4:
        tips.append(TIPS["days"])
    if data.get("left_too_loud"):
        tips.append(TIPS["loud_left"])
    unlocked = set(unlocked)
    seen, out_tips = set(), []
    for t in tips:
        if t not in seen:
            seen.add(t)
            out_tips.append(render_text(t, unlocked))
    return {"title": "Your week", "lines": [render_text(x, unlocked) for x in lines], "tips": out_tips[:3]}


def all_texts() -> list[str]:
    """Every rule text with sample values (the Rule 6 and sentence checks)."""
    sample = {"today": "2026-11-14", "days": [], "practice_days": 3, "minutes": 42, "sessions": 2, "streak": 3,
              "level": 9, "songs": [{"title": "Song", "runs": 2, "best_score": 88, "best_wait": None}],
              "songs_done": ["Song"], "ear_games": 2, "ear_score": 80,
              "skills": [{"id": "rhythm", "name": "Timing", "value": 50}, {"id": "keys", "name": "Find the keys", "value": 90}],
              "left_too_loud": 1}
    r = rule_summary(sample)
    zero = rule_summary({**sample, "practice_days": 0, "minutes": 0, "streak": 0, "songs": [], "songs_done": [],
                         "ear_games": 0, "skills": []})
    return r["lines"] + zero["lines"] + list(TIPS.values()) + [NOT_RUNNING, NO_MODEL.format(model="x")]


# ---------------------------------------------------------------------- Ollama (optional)


def _port() -> int:
    try:
        return int(os.environ.get("RIYAZ_OLLAMA_PORT", str(DEFAULT_PORT)))
    except ValueError:
        return DEFAULT_PORT


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The coach never follows a redirect: the request stays on this Mac (127.0.0.1)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "Redirect refused", headers, fp)


def _opener():
    # No proxy and no redirect: the request goes to this Mac only.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _sock(res):
    """The socket of an open response (CPython), or None."""
    try:
        return res.fp.raw._sock
    except AttributeError:
        return None


def _plain_words(text: str, unlocked) -> str:
    """The LLM text with the plain word for each locked music term (PLAN 7.4 Rule 2)."""
    from .course import _plain_for, content

    def plain(t: dict, shown: str) -> str:
        if t["id"] == "major_minor" and shown.lower() == "minor":  # one plain word for each of the 2 words
            return "Sad sound" if shown[:1].isupper() else "sad sound"
        return _plain_for(t, shown)  # plain_plural for the plural, the capital letter kept

    for t in content()["terms"]:
        if t["id"] in unlocked:
            continue
        text = re.sub(rf"\b(?:{t['pattern']})\b", lambda m, t=t: plain(t, m.group(0)), text, flags=re.I)
    return text


def clean(text: str, unlocked=()) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(text))
    text = re.sub(r"[*_#`>]+", "", text)  # no markdown on the page
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return _plain_words(text, set(unlocked))[:MAX_TEXT]


class Coach:
    """Client for the Ollama HTTP API on 127.0.0.1."""

    def __init__(self, port: int | None = None, model: str = DEFAULT_MODEL,
                 status_timeout: float = STATUS_TIMEOUT_S, timeout: float = GENERATE_TIMEOUT_S):
        self.base = f"http://{HOST}:{port or _port()}"
        self.model = model
        self.status_timeout = status_timeout
        self.timeout = timeout

    def _call(self, path: str, body: dict | None, timeout: float) -> dict:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="GET" if body is None else "POST",
                                     headers={"Content-Type": "application/json"})
        # One deadline for the whole request (connect + all reads), not only for each read.
        deadline = time.monotonic() + timeout
        with _opener().open(req, timeout=timeout) as res:
            sock = _sock(res)
            chunks, size = [], 0
            while size < MAX_REPLY:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError("The coach did not answer in time.")
                if sock is not None and sock.fileno() != -1:  # -1: the answer is all read
                    sock.settimeout(left)
                chunk = res.read1(min(65_536, MAX_REPLY - size))  # what is there now, not a full block
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            raw = b"".join(chunks)
        out = json.loads(raw.decode("utf-8", "replace"))
        if not isinstance(out, dict):
            raise ValueError("not an object")
        return out

    def status(self) -> dict:
        """{"running", "models", "model_ok"}. Never raises."""
        try:
            tags = self._call("/api/tags", None, self.status_timeout)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            log.info("Ollama not running at %s (%s)", self.base, exc.__class__.__name__)
            return {"running": False, "models": [], "model_ok": False}
        names = [m.get("name") for m in tags.get("models") or [] if isinstance(m, dict) and isinstance(m.get("name"), str)]
        ok = self.model in names or f"{self.model}:latest" in names
        return {"running": True, "models": names[:50], "model_ok": ok}

    def prompt(self, data: dict, locked_words: list[str]) -> str:
        avoid = ", ".join(locked_words) if locked_words else "none"
        return (
            "You are a kind piano coach for an adult beginner who practices on a keyboard every day.\n"
            "Write a short weekly summary and 3 tips from the practice data below (JSON).\n"
            "Rules: use simple, common words. Write one idea in each sentence. Use at most 20 words in each "
            "sentence. Write tips as commands. Use plain text, no lists with symbols, no headings. "
            "Write at most 6 sentences and then 3 tips. Use only facts from the data. "
            f"Do not use these words: {avoid}.\n\n"
            f"Data: {json.dumps(data, ensure_ascii=False)}\n"
        )

    def summary(self, data: dict, unlocked=()) -> str:
        """The LLM text. Raises CoachUnavailable when Ollama is not there or does not answer."""
        from .course import content

        st = self.status()
        if not st["running"]:
            raise CoachUnavailable(NOT_RUNNING)
        if not st["model_ok"]:
            raise CoachUnavailable(NO_MODEL.format(model=self.model))
        locked = [t["term"] for t in content()["terms"] if t["id"] not in set(unlocked)]
        body = {"model": self.model, "prompt": self.prompt(data, locked), "stream": False,
                "options": {"temperature": 0.3, "num_predict": 400}}
        try:
            out = self._call("/api/generate", body, self.timeout)
        except (OSError, ValueError, urllib.error.URLError) as exc:
            log.warning("Ollama did not answer: %s", exc)
            raise CoachUnavailable(NOT_RUNNING) from exc
        text = out.get("response")
        if not isinstance(text, str) or not text.strip():
            raise CoachUnavailable(NOT_RUNNING)
        return clean(text, unlocked)


def weekly(store: Store, course=None, today: str | None = None, use_llm: bool | None = None,
           coach: Coach | None = None) -> dict:
    """The weekly card: the rule summary, and the LLM text when the coach is on and running."""
    unlocked = set(store.terms())
    data = week_data(store, course, today)
    out = {"data": data, "rule": rule_summary(data, unlocked), "settings": settings(store),
           "llm": None, "coach": "off"}
    on = out["settings"]["enabled"] if use_llm is None else use_llm
    if not on:
        return out
    coach = coach or Coach(model=out["settings"]["model"])
    try:
        out["llm"] = coach.summary(data, unlocked)
        out["coach"] = "ok"
    except CoachUnavailable as exc:
        out["coach"] = "not_running"
        out["coach_text"] = str(exc)
    return out

