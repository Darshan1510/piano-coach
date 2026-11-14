// Today: the daily session (PLAN 9.1) and the habit card (PLAN 9.2: streak, streak freeze,
// daily goal, practice calendar). The backend makes the plan (riyaz/session.py).

import { DrillPanel } from "/static/js/drill.js";
import { esc } from "/static/js/terms.js";

const $ = (id) => document.getElementById(id);
const FLAME = '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3c1 4 5 5 5 10a5 5 0 0 1-10 0c0-3 2-4 2-6 2 1 3 2 3 4 1-2 0-5 0-8z"/></svg>';
const OK_PATH = '<path d="M5 12l5 5 9-10"/>';
const SKIP_PATH = '<path d="M6 6l8 6-8 6zM16 6v12"/>';
const ICON_OK = `<svg class="icon" viewBox="0 0 24 24">${OK_PATH}</svg>`;
const BLOCK = {
  warmup: { title: "Warm-up", icon: '<path d="M4 14c2-6 6-9 8-9s6 3 8 9"/><path d="M8 19h8"/>' },
  song: { title: "Your song", icon: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>' },
  review: { title: "Review", icon: '<path d="M4 12a8 8 0 1 0 3-6.2"/><path d="M4 4v5h5"/>' },
  intuition: { title: "Find the key", icon: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>' },
};

export function minutesText(min) {
  if (min < 1) return "Less than 1 min";
  const m = Math.round(min);
  return `${m} min`;
}

function clock(s) {
  const v = Math.max(0, Math.round(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
}

// The practice calendar (heat map). Today and Progress both use it.
export function renderCalendar(el, calendar, today) {
  el.innerHTML = "";
  for (const c of calendar.cells) {
    const i = document.createElement("i");
    i.className = `cal-cell l${c.level}${c.frozen ? " frozen" : ""}${c.future ? " future" : ""}${c.day === today ? " today" : ""}`;
    i.title = c.future ? "" : `${c.day}: ${c.frozen ? "free day (streak freeze)" : minutesText(c.minutes)}`;
    el.appendChild(i);
  }
}

const FOCUS = { left: "your left hand", right: "your right hand", coordination: "both hands together",
  rhythm: "your timing", keys: "finding the keys" };

function partName(song, section) {
  return section === null || section === undefined ? "the whole song" : `Part ${section + 1}`;
}

export class TodayScreen {
  constructor({ link, api, piano, terms, reducedMotion, celebrate, openSong, showScreen, onHabit, onTick }) {
    this.api = api;
    this.terms = terms;
    this.celebrate = celebrate;
    this.openSong = openSong;
    this.showScreen = showScreen;
    this.onHabit = onHabit || (() => {});
    this.onTick = onTick || (() => {});
    this.reducedMotion = reducedMotion;
    this.data = null;
    this.session = null;
    this.index = 0;
    this.blockT0 = null; // performance.now() at block time 0 (hidden time is added to it)
    this.hiddenAt = null; // performance.now() when the window was hidden (the timer pauses)
    this.pausedS = 0; // seconds of this block with the window hidden (kept by the server)
    this.lastFrame = performance.now();
    this.activityDone = false;
    this.stepsDone = new Set();
    this.minutes = null;
    this.panel = new DrillPanel($("today-drill"), { link, api, piano, reducedMotion });
    $("today-start").addEventListener("click", () => this.start());
    $("today-basics").addEventListener("click", () => this.showScreen("basics"));
    $("today-next").addEventListener("click", () => this.next("done"));
    $("today-skip").addEventListener("click", () => this.next("skipped"));
    $("today-drill-start").addEventListener("click", () => this._startDrill());
    $("today-sum-learn").addEventListener("click", () => this.showScreen("learn"));
    $("today-sum-again").addEventListener("click", () => { this.summary = null; this.render(); });
    for (const b of document.querySelectorAll("#today-length .seg")) {
      b.addEventListener("click", () => { this.minutes = Number(b.dataset.min); this.render(); });
    }
    link.on("course", (e) => this._onCourse(e));
    setInterval(() => this._tick(), 1000);
    // The block timer pauses while the window is hidden, like the song (PLAN 9.1).
    document.addEventListener("visibilitychange", () => (document.hidden ? this._hide() : this._unhide()));
    window.addEventListener("pagehide", () => this._hide());
    const frame = () => { this.lastFrame = performance.now(); requestAnimationFrame(frame); };
    requestAnimationFrame(frame);
  }

  get active() {
    return !!(this.session && !this.session.ended);
  }

  get block() {
    return this.session ? this.session.plan.blocks[this.index] : null;
  }

  async show() {
    await this._load();
  }

  hide() {
    this.panel.stop();
  }

  async _load() {
    try {
      this.data = await this.api("/api/today");
    } catch {
      return;
    }
    if (!this.data.session && this.active) {
      this.session = null; // the server closed it (a session of an earlier day)
      this.panel.stop();
    }
    if (this.data.session && (!this.session || this.session.id !== this.data.session.id)) {
      this.session = this.data.session;
      const left = this.session.blocks.findIndex((b) => b.status !== "done" && b.status !== "skipped");
      if (left < 0) { // all steps are done or skipped (reload before "Finish"): show the summary
        await this.finish();
        return;
      }
      this.index = left;
      this._enterBlock();
    }
    if (!this.minutes) this.minutes = this.data.habit.session_minutes;
    this.onHabit(this.data.habit);
    this.render();
  }

  // ------------------------------------------------------------------ rendering

  render() {
    const d = this.data;
    if (!d) return;
    this._renderHabit(d.habit);
    const active = this.active;
    const plan = active ? this.session.plan : d.plan;
    const total = active ? plan.minutes : this.minutes;
    const shares = { warmup: 0.1, song: 0.6, review: 0.15, intuition: 0.15 };
    $("today-sub").textContent = active
      ? `${total} minutes. Do the 4 steps in order. Click "Next" after each step.`
      : `${total} minutes: a warm-up, your song, a review and a key game.`;
    $("today-length-row").classList.toggle("hidden", active);
    $("today-plan").classList.toggle("is-compact", active); // while the session runs: a small strip below the block
    this._renderLength();
    const list = $("today-blocks");
    list.innerHTML = "";
    plan.blocks.forEach((b, i) => {
      const st = active ? (this.session.blocks[i] || {}).status : null;
      const now = active && i === this.index;
      const mins = active ? b.minutes : Math.max(0.5, Math.round(total * shares[b.kind] * 2) / 2);
      const li = document.createElement("li");
      li.className = `today-block${now ? " now" : ""}${st === "done" ? " done" : ""}${st === "skipped" ? " skipped" : ""}`;
      li.dataset.kind = b.kind;
      li.innerHTML = `<span class="today-block-icon"><svg class="icon" viewBox="0 0 24 24">${st === "done" ? OK_PATH : st === "skipped" ? SKIP_PATH : BLOCK[b.kind].icon}</svg></span>
        <span class="today-block-main"><b>${BLOCK[b.kind].title}</b><span class="muted">${esc(this._detail(b))}</span></span>
        <span class="today-block-min">${mins % 1 ? mins.toFixed(1) : mins} min</span>`;
      list.appendChild(li);
    });
    const basicsFirst = !active && !this.summary && d.plan && !this._basicsDone();
    $("today-basics-note").classList.toggle("hidden", !basicsFirst);
    $("today-start").classList.toggle("hidden", active || !!this.summary);
    $("today-start").classList.toggle("primary", !basicsFirst);
    $("today-start").textContent = d.finished.length ? "Start a new practice" : "Start today's practice";
    $("today-block").classList.toggle("hidden", !active);
    $("today-summary").classList.toggle("hidden", !this.summary);
    $("today-plan").classList.toggle("hidden", !!this.summary);
    if (this.summary) this._renderSummary(this.summary);
    if (active) this._renderBlock();
  }

  _basicsDone() {
    return !!(this._course && this._course.basics.done);
  }

  setCourse(c) {
    this._course = c;
  }

  _renderLength() {
    for (const b of document.querySelectorAll("#today-length .seg")) b.setAttribute("aria-checked", String(Number(b.dataset.min) === this.minutes));
  }

  _detail(b) {
    if (b.kind === "warmup") return `A short part of "${b.title}", slowly${b.focus && FOCUS[b.focus] ? `. It helps ${FOCUS[b.focus]}` : ""}`;
    if (b.kind === "song") return b.hard_part !== null && b.hard_part !== undefined ? `"${b.title}": Part ${b.hard_part + 1} first, then the whole song` : `"${b.title}"`;
    if (b.kind === "review") return `${partName(null, b.section)[0].toUpperCase()}${partName(null, b.section).slice(1)} of "${b.title}"`;
    return "The app names a key. You press it.";
  }

  _renderBlock() {
    const b = this.block;
    const i = this.index;
    $("today-block-title").textContent = `${i + 1}. ${BLOCK[b.kind].title}`;
    $("today-block-eyebrow").textContent = `Step ${i + 1} of ${this.session.plan.blocks.length}`;
    const text = $("today-block-text");
    const steps = $("today-steps");
    steps.innerHTML = "";
    $("today-drill-wrap").classList.toggle("hidden", !(b.kind === "warmup" || b.kind === "intuition"));
    if (b.kind === "warmup") {
      text.textContent = `Play this short part of "${b.title}" 3 times. Play slowly. Look at the finger numbers.`;
    } else if (b.kind === "intuition") {
      text.textContent = "The app names a key. Press any key with this name on your keyboard, as fast as you can. There are 10 keys to find.";
    } else if (b.kind === "song") {
      text.textContent = `Practice "${b.title}". The song waits for you at each key. When the song needs a new skill, it stops and shows you the skill.`;
      b.steps.forEach((st, k) => steps.appendChild(this._stepButton(b, st, k)));
    } else {
      text.textContent = b.why === "due"
        ? `Play ${partName(null, b.section)} of "${b.title}" along with the song. You learned this song. Today the app asks you to play it again, so that you keep it.`
        : b.why === "done_song"
        ? `Play ${partName(null, b.section)} of "${b.title}" again. You finished this song before. Playing it again helps you keep it.`
        : `You have no finished song yet. Play ${partName(null, b.section)} of "${b.title}" again.`;
      steps.appendChild(this._stepButton(b, { section: b.section, speed: null, label: "review", mode: b.mode || "wait" }, 0));
    }
    $("today-next").textContent = i === this.session.plan.blocks.length - 1 ? "Finish" : "Next";
    this._renderTimer();
  }

  _stepButton(b, st, k) {
    const done = this.stepsDone.has(k);
    const btn = document.createElement("button");
    btn.className = `btn btn-lg today-step${done ? " done" : ""}${!done && [...Array(k).keys()].every((x) => this.stepsDone.has(x)) ? " primary" : ""}`;
    const label = st.label === "hard_part" ? `Practice Part ${st.section + 1} slowly (60% speed)`
      : st.label === "whole" ? (st.mode === "play" ? "Play the whole song along" : "Play the whole song")
      : `Practice ${partName(null, st.section)}`;
    btn.innerHTML = `${done ? ICON_OK : `<span class="today-step-num">${k + 1}</span>`}<span></span>`;
    btn.querySelector("span:last-child").textContent = label;
    btn.addEventListener("click", () => {
      this.openSong(b.song_id, { returnTo: "today", preset: { mode: st.mode || "wait", hands: b.hands, section: st.section, speed: st.speed ?? undefined, loop: false } });
    });
    return btn;
  }

  _enterBlock() {
    this.panel.stop();
    this.activityDone = false;
    this.stepsDone = new Set();
    const b = this.block;
    if (!b) return;
    // Time of this block so far: from its server start time (a reload keeps the timer), less the
    // time with the window hidden; else the saved seconds.
    const saved = this.session.blocks[this.index] || {};
    this.pausedS = saved.paused || 0;
    let elapsed = saved.seconds || 0;
    if (typeof saved.started === "number") elapsed = Math.max(elapsed, Date.now() / 1000 - saved.started - this.pausedS);
    this.hiddenAt = document.hidden ? performance.now() : null;
    this.blockT0 = performance.now() - Math.max(0, elapsed) * 1000;
    if (this.session) this.api(`/api/session/${this.session.id}/block`, { index: this.index, status: "active" }).catch(() => {});
    if (b.kind === "warmup") {
      const p = b.pattern;
      const pitches = b.drill.steps.flatMap((s) => s.any || s.all || []);
      this.panel.setup({ pitches, positions: p.hand_positions, stepBeats: this._stepBeats(b) });
      $("today-drill-start").textContent = "Start";
      setTimeout(() => this._startDrill(), 0);
    } else if (b.kind === "intuition") {
      this.panel.setup({ low: 36, high: 96 });
      $("today-drill-start").textContent = "Start";
    }
  }

  _stepBeats(b) {
    // beat of each warm-up step (for the hand outline): the song notes from the pattern start
    const from = b.pattern.from_beat || 0;
    return b.drill.steps.map((_, i) => from + i);
  }

  async _startDrill() {
    const b = this.block;
    if (!b || !this.session) return;
    $("today-drill-start").textContent = "Start again";
    try {
      await this.panel.start({ source: "session", session_id: this.session.id, block: this.index }, {
        onPass: () => { this.activityDone = true; this._renderTimer(); },
      });
    } catch (err) {
      console.error(err);
    }
  }

  _onCourse(e) {
    if (e.event !== "run" || !this.active) return;
    const b = this.block;
    if (!b || (b.kind !== "song" && b.kind !== "review") || e.song_id !== b.song_id) return;
    if (b.kind === "song") {
      b.steps.forEach((st, k) => { if ((st.section === null) === !!e.full) this.stepsDone.add(k); });
      if (b.steps.every((_, k) => this.stepsDone.has(k))) this.activityDone = true;
    } else {
      this.stepsDone.add(0);
      this.activityDone = true;
    }
    this.lastRun = e;
    if (document.getElementById("screen-today") && !document.getElementById("screen-today").classList.contains("hidden")) this.render();
  }

  // ------------------------------------------------------------------ timer

  _elapsed() {
    if (this.blockT0 === null) return 0;
    return ((this.hiddenAt ?? performance.now()) - this.blockT0) / 1000;
  }

  _left() {
    if (!this.active || this.blockT0 === null) return null;
    return this.block.minutes * 60 - this._elapsed();
  }

  _hide() {
    if (this.active && this.hiddenAt === null) this.hiddenAt = performance.now();
  }

  _unhide() {
    if (this.hiddenAt === null || document.hidden) return;
    const gap = performance.now() - this.hiddenAt;
    this.hiddenAt = null;
    if (!this.active) return;
    this.blockT0 += gap;
    this.pausedS += gap / 1000;
    this.api(`/api/session/${this.session.id}/block`, { index: this.index, status: "active", paused: this.pausedS }).catch(() => {});
  }

  _tick() {
    if (!this.active) { this.onTick(null); return; }
    // No animation frame for 1.5 s: the window is behind other windows or minimized (no
    // visibilitychange then in WKWebView). Pause the timer as for a hidden window.
    if (!document.hidden && performance.now() - this.lastFrame > 1500) this._hide();
    else if (!document.hidden && this.hiddenAt !== null) this._unhide();
    // While hidden, tell the server the hidden time now and then, so a reload keeps it.
    if (this.hiddenAt !== null && performance.now() - (this._pausedSent || 0) > 5000) {
      this._pausedSent = performance.now();
      const paused = this.pausedS + (performance.now() - this.hiddenAt) / 1000;
      this.api(`/api/session/${this.session.id}/block`, { index: this.index, status: "active", paused }).catch(() => {});
    }
    this._renderTimer();
    const left = this._left();
    this.onTick(`${BLOCK[this.block.kind].title}: ${left > 0 ? `${clock(left)} left` : "time is up"}`);
  }

  _renderTimer() {
    if (!this.active) return;
    const left = this._left();
    const total = this.block.minutes * 60;
    $("today-timer-text").textContent = left > 0 ? `${clock(left)} left` : "Time is up. Click \"Next\".";
    $("today-timer-fill").style.width = `${Math.min(100, (100 * (total - Math.max(0, left))) / total)}%`;
    const ready = this.activityDone || left <= 0;
    $("today-next").classList.toggle("primary", ready);
    $("today-block-status").textContent = this.activityDone ? "Done. Click \"Next\"." : "";
    $("today-block-status").className = `today-block-status${this.activityDone ? " ok" : ""}`;
  }

  // ------------------------------------------------------------------ actions

  async start() {
    try {
      this.summary = null;
      this.session = await this.api("/api/session/start", { minutes: this.minutes });
      this.index = 0;
      this._enterBlock();
      this.render();
    } catch (err) {
      console.error(err);
    }
  }

  async next(status) {
    if (!this.active) return;
    const seconds = this._elapsed();
    this.panel.stop();
    this.session = await this.api(`/api/session/${this.session.id}/block`, {
      index: this.index, status, seconds,
      result: this.lastRun && this.lastRun.song_id === this.block.song_id
        ? { accuracy: this.lastRun.accuracy ?? null, score: this.lastRun.score ? this.lastRun.score.total : null } : null,
    });
    if (this.index + 1 < this.session.plan.blocks.length) {
      this.index += 1;
      this._enterBlock();
      this.render();
      return;
    }
    await this.finish();
  }

  async finish() {
    const s = await this.api(`/api/session/${this.session.id}/end`, {});
    this.session = null;
    this.summary = s.summary;
    this.onTick(null);
    await this._load();
    this.render();
    this.celebrate($("today-sum-title"));
  }

  _renderSummary(sum) {
    $("today-sum-time").textContent = minutesText(sum.minutes);
    $("today-sum-skill").textContent = sum.new_skills.length ? sum.new_skills.join(", ") : "None today";
    $("today-sum-best").textContent = sum.best ? `${Math.round(sum.best.accuracy)}%` : "—";
    $("today-sum-best-hint").textContent = sum.best
      ? `Keys right the first time in "${sum.best.title}"${sum.best.whole ? "" : " (one part)"}.` : "Play a song to see a result.";
    $("today-sum-streak").innerHTML = `${FLAME}<span>${sum.streak} day${sum.streak === 1 ? "" : "s"}</span>`;
    $("today-sum-find").textContent = sum.find_key_seconds ? `Find the key: ${sum.find_key_seconds} seconds for each key.` : "";
    $("today-sum-text").textContent = `You did ${sum.blocks_done} of 4 steps. Practice time today: ${minutesText(sum.day_minutes)}.`;
  }

  _renderHabit(h) {
    const st = h.streak;
    $("habit-streak").innerHTML = `<span class="flame${st.days > 0 ? " lit" : ""}">${FLAME}</span><span class="habit-streak-num">${st.days}</span><span class="habit-streak-word">day${st.days === 1 ? "" : "s"} in a row</span>`;
    $("habit-freeze").textContent = st.freeze_left
      ? "You have 1 free day this week. If you miss one day, your streak stays."
      : "You used the free day of this week. Practice every day to keep your streak.";
    if (!st.today_done && st.days > 0) $("habit-freeze").textContent += " Practice today to make it longer.";
    const pct = Math.min(100, (100 * h.today_minutes) / h.goal_minutes);
    $("habit-goal-text").textContent = `${Math.floor(h.today_minutes)} of ${h.goal_minutes} minutes today`;
    $("habit-goal-fill").style.width = `${pct}%`;
    $("habit-goal").classList.toggle("met", pct >= 100);
    renderCalendar($("habit-calendar"), h.calendar, this.data.day);
  }
}
