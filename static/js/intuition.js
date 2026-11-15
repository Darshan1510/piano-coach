// Intuition exercises (PLAN 10): ear and pattern games on the real keyboard.
// The backend (riyaz/intuition.py) makes the rounds, checks the keys and the buttons, and sends
// "intuition" events. This panel plays the sound of each round (Mac sound; or the keyboard
// speaker, sent by the backend), shows the question, the buttons, the keyboard and the result.
// The Intuition page (NAV "Ear") lists the exercises; the daily session uses the same panel.
// Texts with music words come from the server (term marks, PLAN 7.4): this file has no locked word.

import { Keyboard } from "/static/js/keyboard.js";
import { DrillPanel } from "/static/js/drill.js";
import { esc } from "/static/js/terms.js";

const $ = (id) => document.getElementById(id);
const SHOW_MS = 2400; // the answer glows this long after "shown"
const LOOKAHEAD_S = 0.5; // the sound is given to Tone.js this much before its time

const MSG = {
  listen: "Listen.",
  answer: "Your turn.",
  replay: "Listen again.",
  hit: "Good. Go on.",
  right: "Right!",
  wrong: "Not this one. Try again.",
  shown: "Here is the answer. Look at the keys that glow.",
  own: "The app listens to your tune.",
  short: "Play 4 keys or more first.",
  tune_done: "Now play the keys that glow.",
  jam: "Play keys that glow, when you like.",
};

export class IntuitionPanel {
  constructor(el, { link, api, piano, terms, reducedMotion, celebrate }) {
    this.el = el;
    this.link = link;
    this.api = api;
    this.piano = piano;
    this.terms = terms;
    this.reducedMotion = reducedMotion;
    this.celebrate = celebrate || (() => {});
    this.run = null;
    this.state = null;
    this.played = null; // play_at of the sound that is scheduled (the same sound is not played 2 times)
    this.onDone = null;
    el.classList.add("ix");
    el.innerHTML = `
      <div class="ix-top">
        <div class="ix-dots" aria-hidden="true"></div>
        <div class="ix-count muted"></div>
        <div class="ix-msg" role="status" aria-live="polite"></div>
      </div>
      <p class="ix-prompt"></p>
      <div class="ix-actions">
        <button class="btn ix-replay" type="button">Listen again</button>
        <div class="ix-choices" role="group" aria-label="Answers"></div>
        <button class="btn ix-tune hidden" type="button">My tune is done</button>
      </div>
      <div class="ix-jam hidden" aria-live="off"><span class="ix-jam-now"></span><div class="ix-jam-line"><i></i></div><span class="ix-jam-count muted"></span></div>
      <div class="dr-kb ix-kb"><div class="keyboard-wrap pr-keyboard"></div></div>
      <div class="ix-result hidden">
        <div class="ix-score"><b></b><span>points of 100</span></div>
        <p class="ix-result-text"></p>
        <div class="ix-result-btns"><button class="btn primary ix-again" type="button">Play again</button></div>
      </div>`;
    this.$dots = el.querySelector(".ix-dots");
    this.$count = el.querySelector(".ix-count");
    this.$msg = el.querySelector(".ix-msg");
    this.$prompt = el.querySelector(".ix-prompt");
    this.$replay = el.querySelector(".ix-replay");
    this.$choices = el.querySelector(".ix-choices");
    this.$tune = el.querySelector(".ix-tune");
    this.$jam = el.querySelector(".ix-jam");
    this.$result = el.querySelector(".ix-result");
    this.$again = el.querySelector(".ix-again");
    this.kb = new Keyboard(el.querySelector(".keyboard-wrap"), {
      low: 36, high: 96,
      onPress: (p) => { this.kb.setDown(p, true); this.piano.play(p); },
      onRelease: (p) => this.kb.setDown(p, false),
    });
    this.kb.showAllNames(true);
    this.$replay.addEventListener("click", () => this._post("/api/intuition/replay"));
    this.$tune.addEventListener("click", () => this._post("/api/intuition/tune-done"));
    this.$again.addEventListener("click", () => this.again && this.again());
    link.on("intuition", (s) => { if (this.run !== null && s.run === this.run) this._onState(s); });
    link.on("intuition_wrong", (e) => { if (this.run !== null && e.run === this.run && e.pitch) this._flash(e.pitch, "wrong"); });
    link.on("note_on", (e) => this.kb.setDown(e.pitch, true));
    link.on("note_off", (e) => this.kb.setDown(e.pitch, false));
    setInterval(() => this._jamTick(), 200);
  }

  get active() {
    return !!(this.state && this.run !== null && !["done", "stopped", "idle"].includes(this.state.status));
  }

  async start(body, { onDone = null, again = null } = {}) {
    this.onDone = onDone;
    this.again = again;
    this.played = null;
    this._quiet(); // no sound of the run before
    this._clearShow();
    // Sound starts in this click. Do not wait long: without a click (checks) it never starts.
    if (!this.piano.started) await Promise.race([this.piano.start().catch(() => {}), new Promise((r) => setTimeout(r, 300))]);
    this.$result.classList.add("hidden");
    const s = await this.api("/api/intuition/start", body);
    this.run = s.run;
    this._onState(s);
    return s;
  }

  stop() {
    if (this.run === null) return;
    this.run = null;
    this._quiet();
    this._clearShow();
    this._marks([], [], []);
    this.api("/api/intuition/stop", {}).catch(() => {});
  }

  _post(path) {
    if (this.run === null) return;
    this.api(path, { run: this.run }).catch(() => {});
  }

  // ------------------------------------------------------------------ state

  _onState(s) {
    if (this.state && this.state.run === s.run && s.seq < this.state.seq) return;
    const prev = this.state && this.state.run === s.run ? this.state : null;
    this.state = s;
    if (s.status === "stopped") this._quiet(); // stopped by the app (for example, a song starts)
    const hasSound = (s.play && s.play.length) || (s.clicks && s.clicks.length);
    if (hasSound && s.play_at && s.play_at !== this.played && ["listen", "answer", "jam"].includes(s.status)) {
      this.played = s.play_at;
      // Keyboard speaker: the app sends the notes to the keyboard; the clicks play on the Mac.
      this._sound(s, s.output === "keyboard");
    }
    this._render(s, prev);
  }

  _render(s, prev) {
    const done = s.status === "done";
    const graded = s.graded_rounds || s.rounds;
    // Progress: one dot for each round (green = right the first time).
    const first = (s.result && s.result.first) || null;
    this.$dots.innerHTML = Array.from({ length: s.rounds }, (_, i) => {
      // A round with no right or wrong (the tune of "Add chords": null), or no entry: "past".
      const mark = first && i < first.length && first[i] !== null && first[i] !== undefined ? (first[i] ? "ok" : "miss") : "past";
      const cls = i < s.round || done ? mark : i === s.round ? "now" : "";
      return `<i class="${cls}"></i>`;
    }).join("");
    const jam = s.solution && s.solution.mode === "jam";
    this.$count.textContent = done || jam ? "" : `${Math.min(s.round + 1, s.rounds)} of ${s.rounds}`;
    this.$prompt.innerHTML = s.prompt ? this._markup(s.prompt) : "";
    // Buttons.
    // The answer buttons are made again only for a new round (the focus stays on the button).
    const canAnswer = s.status === "answer" || s.status === "listen";
    const choiceKey = `${s.run}:${s.round}:${(s.choices || []).map((c) => c.id).join(",")}`;
    if (this._choiceKey !== choiceKey) {
      this._choiceKey = choiceKey;
      this.$choices.innerHTML = "";
      for (const c of s.choices || []) {
        const b = document.createElement("button");
        b.className = "btn btn-lg ix-choice";
        b.type = "button";
        b.dataset.choice = c.id;
        b.innerHTML = this._markup(c.label);
        b.addEventListener("click", () => this.api("/api/intuition/answer", { run: this.run, choice: c.id }).catch(() => {}));
        this.$choices.appendChild(b);
      }
    }
    for (const b of this.$choices.querySelectorAll(".ix-choice")) {
      b.disabled = !canAnswer;
      b.classList.toggle("is-answer", s.last === "shown" && !!s.solution && s.solution.choice === b.dataset.choice);
    }
    this.$replay.classList.toggle("hidden", !(s.play && s.play.length) || jam || done);
    this.$replay.disabled = !canAnswer;
    this.$tune.classList.toggle("hidden", !(s.phase === "tune" && s.status === "answer"));
    this.$jam.classList.toggle("hidden", !jam || done);
    // Message.
    let msg = MSG[s.last] || (s.status === "listen" ? MSG.listen : s.status === "answer" ? MSG.answer : jam ? MSG.jam : "");
    if (s.status === "listen" && s.last !== "right" && s.last !== "shown") msg = MSG.listen;
    const tone = s.last === "right" ? "ok" : s.last === "wrong" || s.last === "short" ? "bad" : s.last === "shown" ? "warn" : "go";
    this.$msg.textContent = done ? "" : msg;
    this.$msg.className = `ix-msg ${tone}`;
    // Keys that glow.
    const sol = s.solution || {};
    let target = [];
    let family = [];
    let answer = [];
    if (jam) family = s.glow || [];
    else if (s.phase === "tune" && s.status === "answer") target = sol.keys && sol.keys[s.step] ? sol.keys[s.step] : [];
    else if (s.phase === "chord" && s.status === "answer") target = s.glow || [];
    else if (sol.mode === "find" && s.status === "answer") target = s.step === 0 || s.misses >= 3 ? sol.keys[s.step] || [] : [];
    if (s.last === "shown" && prev && prev.last !== "shown") this._showAnswer(sol.keys ? sol.keys.flat() : []);
    if (!this._showing) this._marks(target, family, answer);
    if (s.last === "right" && prev && prev.last !== "right") this._flashAll(sol.keys ? sol.keys.flat() : [], "hit");
    if (done) this._done(s, prev);
  }

  _done(s, prev) {
    const r = s.result || {};
    this.$result.classList.remove("hidden");
    this.$result.querySelector("b").textContent = Math.round(r.score ?? 0);
    this.$result.querySelector(".ix-result-text").innerHTML = this._markup(r.text || "");
    this.$again.classList.toggle("hidden", !this.again);
    this._marks([], [], []);
    if (prev && prev.status !== "done") {
      if ((r.score ?? 0) >= 80) this.celebrate(this.$result.querySelector(".ix-score"));
      const cb = this.onDone;
      if (cb) cb(s);
    }
  }

  _markup(text) {
    return this.terms ? this.terms.markup(text) : esc(text);
  }

  // ------------------------------------------------------------------ sound

  // Sound: the notes and clicks of a round go in a queue. A timer gives Tone.js only the events
  // of the next LOOKAHEAD_S seconds, so that "Back" or a new run stops the sound at once (no old
  // chord or click plays later; Tone.js cannot take back events that it has already got).
  _quiet() {
    this._queue = [];
    clearInterval(this._soundTimer);
    this._soundTimer = null;
    try {
      this.piano.releaseAll();
      if (this.piano.click) { this.piano.click.dispose(); this.piano.click = null; }
    } catch (err) {
      console.error(err);
    }
  }

  _sound(s, clicksOnly = false) {
    if (!this.piano.started) return;
    this._quiet();
    const sNow = this.link.serverNow();
    const aNow = this.piano.audioNow();
    const queue = [];
    for (const n of clicksOnly ? [] : s.play || []) {
      const when = aNow + (s.play_at + n.t - sNow);
      if (when + n.dur < aNow) continue;
      queue.push({ when: Math.max(aNow, when), pitch: n.pitch, dur: n.dur });
    }
    (s.clicks || []).forEach((t, i) => {
      const when = aNow + (s.play_at + t - sNow);
      if (when >= aNow) queue.push({ when, click: true, accent: i % 4 === 0 });
    });
    queue.sort((a, b) => a.when - b.when);
    this._queue = queue;
    this._feed();
    if (queue.length) this._soundTimer = setInterval(() => this._feed(), 100);
  }

  _feed() {
    const q = this._queue || [];
    const until = this.piano.audioNow() + LOOKAHEAD_S;
    while (q.length && q[0].when <= until) {
      const e = q.shift();
      try {
        if (e.click) this.piano.clickAt(e.when, e.accent);
        else this.piano.playAt(e.pitch, e.when, e.dur, 78);
      } catch (err) {
        console.error(err);
      }
    }
    if (!q.length) { clearInterval(this._soundTimer); this._soundTimer = null; }
  }

  _jamTick() {
    const s = this.state;
    if (!s || this.run === null || s.status !== "jam" || !s.length) return;
    const now = this.link.serverNow() - s.play_at;
    const frac = Math.max(0, Math.min(1, now / s.length));
    this.$jam.querySelector("i").style.width = `${frac * 100}%`;
    const chord = [...(s.chords || [])].reverse().find((c) => c.t <= now) || (s.chords || [])[0];
    this.$jam.querySelector(".ix-jam-now").textContent = chord ? chord.name : "";
    const j = s.jam || { presses: 0, inside: 0 };
    this.$jam.querySelector(".ix-jam-count").textContent = `${j.inside} of ${j.presses} keys from the family`;
    this.kb.setMarked("play-L", chord && now >= 0 ? chord.keys : []);
  }

  // ------------------------------------------------------------------ keys

  _marks(target, family, answer) {
    this.kb.setMarked("target-R", target);
    this.kb.setMarked("family", family);
    this.kb.setMarked("target-L", answer);
    if (!family.length) this.kb.setMarked("play-L", []);
  }

  _showAnswer(keys) {
    this._clearShow();
    this._showing = true;
    this._marks([], [], keys);
    this._showT = setTimeout(() => { this._showing = false; if (this.state) this._render(this.state, this.state); }, SHOW_MS);
  }

  _clearShow() {
    clearTimeout(this._showT);
    this._showing = false;
  }

  _flash(pitch, cls) {
    this.kb.mark(pitch, cls, true);
    setTimeout(() => this.kb.mark(pitch, cls, false), 350);
  }

  _flashAll(pitches, cls) {
    for (const p of pitches) this._flash(p, cls);
  }
}

// ------------------------------------------------------------------ the page (NAV "Ear")

const ICON_LOCK = '<svg class="icon" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';
const SKILL_WORDS = { keys: "Find the keys", ear: "Play by ear", chords: "Keys together", scales: "Key family" };

export class IntuitionScreen {
  constructor({ link, api, piano, terms, reducedMotion, celebrate, getStatus, onLearn }) {
    this.api = api;
    this.terms = terms;
    this.getStatus = getStatus;
    this.onLearn = onLearn;
    this.data = null;
    this.current = null;
    this.panel = new IntuitionPanel($("ix-panel"), { link, api, piano, terms, reducedMotion, celebrate });
    this.drill = new DrillPanel($("ix-drill"), { link, api, piano, reducedMotion });
    $("ix-back").addEventListener("click", () => this.close());
    $("ix-output").addEventListener("change", () => {
      if (this.current && this.current.kind !== "drill") this.open(this.current);
    });
  }

  async show() {
    try {
      this.data = await this.api("/api/intuition");
    } catch {
      this.data = null;
    }
    if (!this.current) this.render();
  }

  hide() {
    this.panel.stop();
    this.drill.stop();
  }

  render() {
    const el = $("ix-list");
    const d = this.data;
    $("ix-play").classList.add("hidden");
    $("ix-home").classList.remove("hidden");
    el.innerHTML = "";
    if (!d) {
      el.innerHTML = '<div class="card"><p class="muted">The app cannot load the games. Start the app again.</p></div>';
      return;
    }
    for (const ex of d.exercises) {
      const card = document.createElement("article");
      card.className = `card ix-card${ex.open ? "" : " is-locked"}`;
      card.dataset.ex = ex.id;
      const last = ex.last !== null && ex.last !== undefined ? `Last: ${Math.round(ex.last)} points` : ex.open ? "New" : "";
      const skills = ex.skills.map((k) => `<span class="chip">${esc(SKILL_WORDS[k] || k)}</span>`).join("");
      card.innerHTML = `<div class="ix-card-top"><span class="pill ${ex.open ? "pill-level" : "pill-quiet"}">${ex.open ? "" : ICON_LOCK}Level ${ex.level}</span><span class="muted ix-last">${last}</span></div>
        <h3>${this.terms.markup(ex.name)}</h3>
        <p class="muted ix-card-text">${this.terms.markup(ex.text[0])}</p>
        <div class="ix-card-skills">${skills}</div>
        <button class="btn ${ex.open ? "primary" : ""}" ${ex.open ? "" : "disabled"}>${ex.open ? "Start" : `Opens at Level ${ex.level}`}</button>`;
      card.querySelector("button").addEventListener("click", () => this.open(ex));
      el.appendChild(card);
    }
  }

  async open(ex) {
    this.current = ex;
    $("ix-home").classList.add("hidden");
    $("ix-play").classList.remove("hidden");
    $("ix-title").innerHTML = this.terms.markup(ex.name);
    $("ix-text").innerHTML = ex.text.map((t) => `<p>${this.terms.markup(t)}</p>`).join("");
    const st = this.getStatus ? this.getStatus() : {};
    const canKeyboard = !!(st && st.output);
    $("ix-output-row").classList.toggle("hidden", !canKeyboard || ex.kind === "drill");
    if (!canKeyboard) $("ix-output").checked = false;
    $("ix-panel").classList.toggle("hidden", ex.kind === "drill");
    $("ix-drill").classList.toggle("hidden", ex.kind !== "drill");
    $("ix-drill-start").classList.toggle("hidden", ex.kind !== "drill");
    this.panel.stop();
    this.drill.stop();
    if (ex.kind === "drill") {
      this.drill.setup({ low: 36, high: 96 });
      $("ix-drill-start").onclick = () => this.drill.start({ source: "find_key" }, { onPass: () => this.show() });
      return;
    }
    try {
      await this.panel.start({ id: ex.id, output: $("ix-output").checked ? "keyboard" : "mac" }, {
        onDone: () => this.show(),
        again: () => this.open(ex),
      });
    } catch (err) {
      $("ix-text").innerHTML += `<p class="ix-error">${esc(err.message || String(err))}</p>`;
    }
  }

  close() {
    this.panel.stop();
    this.drill.stop();
    this.current = null;
    this.render();
    this.show();
  }
}
