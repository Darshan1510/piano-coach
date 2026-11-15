// Practice screen: falling notes, hand outline, watch mode and wait mode (PLAN 6.3-6.5).
//
// The backend owns the song clock (riyaz/practice.py). Each "practice" event has an anchor:
//   beat = anchor_beat + (server_now - anchor_t) * rate      (clamped at hold_beat in wait mode)
// server_now comes from the clock offset in ws.js (ping/pong, median of 5).
// This module draws that beat at 60 fps and plays the app's notes and the click on the Mac.
//
// Words (PLAN 7.4, Level 1-2): "speed" (not tempo), "the click" (not beat), "Part 1" (not bar),
// "pause", "keys together". No bar lines before Level 3.
//
// Phase 4 play-along (mode "play"): the song does not wait. Keys turn green (on time), yellow
// (early or late) or red (wrong) (PLAN 7.1); one tip at a time from the backend (practice_tip).
// If the user stops, the song pauses at the stop point: "Continue from here". After the run: the
// score, at most 3 findings with a preview, "Show me" and an action button (PLAN 7.2), and the
// automatic speed change (PLAN 7.3).

import { Keyboard, keyLayout, keyName } from "/static/js/keyboard.js";
import { FallingNotes, PreviewView } from "/static/js/renderer.js";
import { HandsView, positionAt, positionsOf } from "/static/js/hands.js";
import { handsText } from "/static/js/songs.js";
import { DrillPanel } from "/static/js/drill.js";
import { esc } from "/static/js/terms.js";

const $ = (id) => document.getElementById(id);
const HAND = { R: "right hand", L: "left hand" };
const LOW = 36;
const HIGH = 96;
const AUDIO_AHEAD_S = 0.15; // schedule Mac notes and clicks this far ahead
const GAP_PAUSE_MS = 1000; // no frame for this long while the song runs = the window was hidden
const MARK_MIN_MS = 250; // a red or green key stays at least this long
const LATE_MAX_S = 0.25; // after a new anchor, a note or click this late still plays (at once)
// Where the back button and the end card go (the screen that opened the song).
const RETURN = {
  songs: { back: "Songs", end: "Select another song" },
  today: { back: "Today", end: "Back to today's practice" },
  learn: { back: "Learn", end: "Back to the course" },
  basics: { back: "Keyboard basics", end: "Back to the keyboard basics" },
};

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function lowerBound(arr, x, key) {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (key(arr[mid]) < x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

// Arrow keys move the choice in a role="radio" group (WAI-ARIA radio group). Only the checked
// button is in the Tab order.
export function radioKeys(group) {
  const items = () => [...group.querySelectorAll('[role="radio"]')].filter((b) => !b.disabled);
  group.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!step) return;
    const list = items();
    const i = list.indexOf(document.activeElement);
    if (i < 0 || !list.length) return;
    e.preventDefault();
    const next = list[(i + step + list.length) % list.length];
    next.focus();
    next.click();
  });
  const sync = () => {
    const list = [...group.querySelectorAll('[role="radio"]')];
    const checked = list.find((b) => b.getAttribute("aria-checked") === "true" && !b.disabled);
    for (const b of list) b.tabIndex = b === (checked || list.find((x) => !x.disabled)) ? 0 : -1;
  };
  new MutationObserver(sync).observe(group, { subtree: true, attributes: true, attributeFilter: ["aria-checked", "disabled"] });
  sync();
}

export class PracticeScreen {
  constructor({ link, piano, api, celebrate, reducedMotion, getStatus, startSound, terms, getCourse, onReturn }) {
    this.terms = terms;
    this.getCourse = getCourse || (() => null);
    this.onReturn = onReturn || (() => {});
    this.returnTo = "songs";
    this.moments = [];
    this.skill = null; // the skill moment on the screen
    this.link = link;
    this.piano = piano;
    this.api = api;
    this.celebrate = celebrate;
    this.reducedMotion = reducedMotion;
    this.getStatus = getStatus;
    this.startSound = startSound;
    this.song = null;
    this.ps = null; // last practice state from the backend (this song)
    this.visible = false;
    this.opts = { mode: "wait", hands: ["R"], section: null, speed: 1, click: false, countIn: true,
      accompany: true, kbSound: false, adapt: true, loopStep: true, span: null };
    this.results = new Map(); // play-along: note id -> "hit" | "miss" (red notes on the view)
    this.place = null; // the place that a finding names (band on the falling notes)
    this.peek = null; // after a run: the view shows this beat (the place of a finding)
    this.marks = { wrong: new Map(), hit: new Map(), timing: new Map() }; // pitch -> time when set
    this.down = new Set();
    this.banner = { text: "", until: 0 };
    this.frameTimes = [];
    this.drawTimes = [];
    this.lastFrame = null;
    this.lastBeat = null;
    this.fallbackOffset = 0;
    this._loadOptions();

    const layout = keyLayout(LOW, HIGH);
    this.kb = new Keyboard($("pr-keyboard"), {
      low: LOW, high: HIGH,
      onPress: (p) => { this.kb.setDown(p, true); this.piano.play(p); },
      onRelease: (p) => this.kb.setDown(p, false),
    });
    this.kb.showAllNames(true);
    this.renderer = new FallingNotes($("pr-canvas"), layout, { showBarLines: false });
    this.skillPanel = new DrillPanel($("pr-skill-drill"), { link, api, piano, reducedMotion });
    this.hands = new HandsView($("pr-hands-canvas"), layout);
    this._bind();
    this._readColors();
    new MutationObserver(() => this._readColors()).observe(document.documentElement,
      { attributes: true, attributeFilter: ["data-theme"] });
    new ResizeObserver(() => this._resize()).observe($("pr-stage"));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) this._pauseHidden("hidden");
    });
    window.addEventListener("pagehide", () => this._pauseHidden("hidden"));
  }

  // ------------------------------------------------------------------ open / close

  // opts: {returnTo: "songs" | "today" | "learn" | "basics", preset: {mode, hands, section, speed}}
  async open(songId, opts = {}) {
    const song = await this.api(`/api/songs/${encodeURIComponent(songId)}`);
    this.returnTo = RETURN[opts.returnTo] ? opts.returnTo : "songs";
    if (this.ps && this.ps.song_id && this.ps.song_id !== song.id) {
      await this.api("/api/practice/stop", {}).catch(() => {});
    }
    this.song = song;
    this.ps = null;
    this.handsPresent = ["R", "L"].filter((h) => song.notes.some((n) => n.hand === h));
    this.opts.hands = this.handsPresent.includes("R") ? ["R"] : [this.handsPresent[0]];
    this.opts.section = null;
    this.opts.span = null;
    this.place = null;
    this.peek = null;
    const pre = opts.preset || {};
    if (pre.mode) this.opts.mode = pre.mode;
    if (Array.isArray(pre.hands) && pre.hands.every((h) => this.handsPresent.includes(h))) this.opts.hands = pre.hands;
    if (Number.isInteger(pre.section) && song.sections[pre.section]) this.opts.section = pre.section;
    if (typeof pre.speed === "number") this.opts.speed = pre.speed;
    if (Array.isArray(pre.span)) this.opts.span = pre.span;
    this.opts.loop = pre.loop === false ? false : null; // daily session: a part plays one time
    this.moments = (await this.api(`/api/course/moments/${encodeURIComponent(song.id)}`).catch(() => ({ moments: [] }))).moments;
    this._hideSkill();
    this.lastResult = null;
    $("pr-back-text").textContent = RETURN[this.returnTo].back;
    $("pr-end-songs").textContent = RETURN[this.returnTo].end;
    this.renderer.setSong(song);
    this.positions = { R: positionsOf(song, "R"), L: positionsOf(song, "L") };
    this.handNotes = {
      R: song.notes.filter((n) => n.hand === "R").sort((a, b) => a.start - b.start),
      L: song.notes.filter((n) => n.hand === "L").sort((a, b) => a.start - b.start),
    };
    $("pr-title").textContent = song.title;
    $("pr-level").textContent = `Level ${song.level}`;
    $("pr-hands-text").textContent = handsText(this.handsPresent, song.source, song.level);
    $("pr-credit").textContent = song.credit || "";
    // Parts (song sections) for "Repeat a part".
    const sel = $("pr-part");
    this._partOptions();
    sel.value = this.opts.section === null ? "" : String(this.opts.section);
    const clicks = song.time_signature[0];
    $("pr-countin-label").textContent = `${clicks} clicks before the start`;
    this._hideEnd();
    this._renderControls();
    this._applyView();
    const st = await this.api("/api/practice").catch(() => null);
    if (st && st.song_id === song.id) this._onState(st);
    return song;
  }

  // Words that change after an unlock (PLAN 7.4): speed -> tempo, the click -> beat, bar numbers.
  refreshWords() {
    if (!this.terms) return;
    $("pr-speed-word").innerHTML = this.terms.html("tempo", { capital: true });
    $("pr-click-word").innerHTML = this.terms.unlocked("beat") ? `The click (the ${this.terms.html("beat")})` : "The click";
    if (this.song) {
      const v = $("pr-part").value;
      this._partOptions();
      $("pr-part").value = v;
    }
    const c = this.getCourse();
    this.renderer.showBarLines = !!(c && c.bar_lines); // PLAN 7.4 Rule 5: from Level 3
  }

  _partOptions() {
    const sel = $("pr-part");
    const song = this.song;
    sel.innerHTML = "";
    sel.appendChild(new Option("All the song", ""));
    const group = song.time_signature[0];
    const bars = this.terms && this.terms.unlocked("bar");
    song.sections.forEach((s, i) => {
      const extra = bars ? ` (${this.terms.word("bar", { plural: true })} ${Math.floor(s.start / group) + 1} to ${Math.ceil(s.end / group)})` : "";
      sel.appendChild(new Option(`Repeat ${s.name}${extra}`, String(i)));
    });
    if (song.loop) sel.appendChild(new Option("Repeat my loop (from the editor)", "loop"));
  }

  show() {
    this.visible = true;
    this.refreshWords();
    this._resize();
    this._renderControls();
    this.lastFrame = null;
    const id = (this._loop = (this._loop || 0) + 1); // one animation loop only (show() can come again)
    requestAnimationFrame((ts) => this._frame(ts, id));
  }

  hide() {
    this.visible = false;
    this._hideSkill();
    this._pauseHidden("left");
    this.piano.releaseAll();
  }

  onStatus() {
    this._renderControls();
  }

  // ------------------------------------------------------------------ controls

  _bind() {
    for (const b of document.querySelectorAll("#pr-mode .seg")) {
      b.addEventListener("click", () => this._setOpt("mode", b.dataset.mode));
    }
    for (const b of document.querySelectorAll("#pr-hands .seg")) {
      b.addEventListener("click", () => this._setOpt("hands", b.dataset.hands.split("")));
    }
    $("pr-part").addEventListener("change", (e) => {
      this.opts.loop = null; this.opts.span = null; this.place = null;
      if (e.target.value === "loop" && this.song.loop) { // the loop from the song editor (Phase 5a)
        this.opts.span = [this.song.loop.start, this.song.loop.end];
        this._setOpt("section", null);
        return;
      }
      this._setOpt("section", e.target.value === "" ? null : Number(e.target.value));
    });
    $("pr-countin").addEventListener("change", (e) => { this._setOpt("countIn", e.target.checked); this._saveOptions(); });
    $("pr-accompany").addEventListener("change", (e) => this._setOpt("accompany", e.target.checked));
    $("pr-kbsound").addEventListener("change", (e) => this._setOpt("kbSound", e.target.checked));
    $("pr-adapt").addEventListener("change", (e) => { this.opts.adapt = e.target.checked; this._saveOptions(); });
    $("pr-loopstep").addEventListener("change", (e) => { this.opts.loopStep = e.target.checked; this._saveOptions(); });
    $("pr-end-next").addEventListener("click", () => this._nextStep());
    $("pr-findings").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]");
      if (b) this._findingButton(Number(b.dataset.i), b.dataset.act);
    });
    $("pr-findings").addEventListener("focusin", (e) => {
      const card = e.target.closest(".pr-finding");
      if (card) this._focusFinding(Number(card.dataset.i));
    });
    $("pr-click").addEventListener("change", (e) => {
      this.opts.click = e.target.checked;
      this._resetAudio();
      this._saveOptions();
    });
    const speed = $("pr-speed");
    speed.addEventListener("input", () => {
      this.opts.speed = Number(speed.value) / 100;
      $("pr-speed-text").textContent = `${speed.value}%`;
    });
    speed.addEventListener("change", () => {
      if (this.ps && (this.ps.running || this.ps.paused)) this.api("/api/practice/speed", { speed: this.opts.speed }).then((s) => this._onState(s));
      this._saveOptions();
    });
    $("pr-start").addEventListener("click", () => this._primary());
    $("pr-restart").addEventListener("click", () => this.start());
    $("pr-end-again").addEventListener("click", () => this.start());
    $("pr-end-play").addEventListener("click", async () => { await this._setOpt("mode", "wait"); this.start(); });
    $("pr-back").addEventListener("click", () => this.onReturn(this.returnTo));
    $("pr-end-songs").addEventListener("click", () => this.onReturn(this.returnTo));
    $("pr-skill-demo").addEventListener("click", () => this._skillDemo());
    $("pr-skill-try").addEventListener("click", () => this._skillTry());
    $("pr-skill-go").addEventListener("click", () => this._skillContinue(true));
    $("pr-skill-skip").addEventListener("click", () => this._skillContinue(false));
    this.link.on("practice_skill", (e) => { if (this._ours(e)) this._showSkill(e.skill, e.beat); });
    this.link.on("course", (e) => { if (e.event === "run" && this.song && e.song_id === this.song.id) this._onResult(e); });
    for (const group of document.querySelectorAll("#pr-mode, #pr-hands")) radioKeys(group);

    this.link.on("practice", (s) => this._onState(s));
    this.link.on("practice_wrong", (e) => { if (this._ours(e)) this._onWrong(e); });
    this.link.on("practice_hit", (e) => {
      if (!this._ours(e)) return;
      // play-along: green on time, yellow early or late (PLAN 7.1)
      this._mark(e.grade === "early" || e.grade === "late" ? "timing" : "hit", e.pitch);
      if (e.note !== undefined && e.note !== null && this.playIds) this.results.set(this.playIds[e.note], "hit");
    });
    this.link.on("practice_miss", (e) => {
      if (this._ours(e) && this.playIds) this.results.set(this.playIds[e.note], "miss");
    });
    this.link.on("practice_tip", (e) => { if (this._ours(e)) this._say(this.terms ? this.terms.plainText(e.text) : e.text, 3500, "tip"); });
    this.link.on("practice_pass", (e) => { if (this._ours(e)) this._onPass(e); });
    this.link.on("practice_end", (e) => this._onEnd(e));
    this.link.on("note_on", (e) => { this.down.add(e.pitch); this.kb.setDown(e.pitch, true); });
    this.link.on("note_off", (e) => {
      this.down.delete(e.pitch);
      this.kb.setDown(e.pitch, false);
      for (const kind of ["wrong", "hit", "timing"]) this._unmarkLater(kind, e.pitch);
    });
  }

  // An event for this song and this run? (Older backends send no song_id or run: accept them.)
  _ours(e) {
    if (!this.song || !this.ps) return false;
    if (e.song_id !== undefined && e.song_id !== this.song.id) return false;
    return e.run === undefined || e.run === this.ps.run;
  }

  // A change of mode, hands, part, count-in or sound stops the song. Speed and the click do not.
  // Returns when the stop is done, so that a start() after it cannot arrive first.
  async _setOpt(name, value) {
    this.opts[name] = value;
    this._hideEnd();
    this._renderControls();
    this._applyView();
    if (this.ps && this.ps.song_id && (this.ps.running || this.ps.paused || this.ps.done)) {
      try {
        this._onState(await this.api("/api/practice/stop", {}));
      } catch { /* the next start shows the problem */ }
    }
  }

  // Speed, the click and the count-in stay after a restart (settings in the app's database).
  async _loadOptions() {
    try {
      const o = await this.api("/api/settings/practice");
      this.opts.speed = o.speed;
      this.opts.click = o.click;
      this.opts.countIn = o.count_in;
      this.opts.adapt = o.adapt !== false;
      this.opts.loopStep = o.loop_step !== false;
      this._renderControls();
      this._applyView();
    } catch { /* keep the defaults */ }
  }

  _saveOptions() {
    const o = this.opts;
    this.api("/api/settings/practice", { speed: o.speed, click: o.click, count_in: o.countIn, adapt: o.adapt,
      loop_step: o.loopStep }).catch(() => {});
  }

  _renderControls() {
    if (!this.song) return;
    const o = this.opts;
    for (const b of document.querySelectorAll("#pr-mode .seg")) b.setAttribute("aria-checked", String(b.dataset.mode === o.mode));
    const handsKey = o.hands.join("");
    for (const b of document.querySelectorAll("#pr-hands .seg")) {
      const need = b.dataset.hands.split("");
      b.disabled = !need.every((h) => this.handsPresent.includes(h));
      b.setAttribute("aria-checked", String(b.dataset.hands === handsKey));
    }
    $("pr-hands-group").classList.toggle("hidden", this.handsPresent.length < 2);
    const other = this.handsPresent.find((h) => !o.hands.includes(h));
    $("pr-accompany-row").classList.toggle("hidden", !other || o.mode === "watch");
    $("pr-adapt-row").classList.toggle("hidden", o.mode !== "play");
    $("pr-adapt").checked = o.adapt;
    $("pr-loopstep-row").classList.toggle("hidden", o.mode !== "play" || (o.section === null && !o.span));
    $("pr-loopstep").checked = o.loopStep;
    if (other) $("pr-accompany-label").textContent = `The app plays the ${HAND[other]}`;
    $("pr-accompany").checked = o.accompany;
    const canKb = !!(this.getStatus().output);
    $("pr-kbsound-row").classList.toggle("hidden", !canKb);
    if (!canKb) o.kbSound = false;
    $("pr-kbsound").checked = o.kbSound;
    $("pr-countin").checked = o.countIn;
    $("pr-click").checked = o.click;
    $("pr-speed").value = String(Math.round(o.speed * 100));
    $("pr-speed-text").textContent = `${Math.round(o.speed * 100)}%`;

    const ps = this.ps;
    const running = ps && ps.running;
    const paused = ps && ps.paused;
    const stopped = paused && ps.pause_reason === "stopped";
    $("pr-start-text").textContent = running ? "Pause" : stopped ? "Continue from here" : paused ? "Continue"
      : o.mode === "wait" ? "Start playing" : o.mode === "play" ? "Start playing along" : "Start watching";
    $("pr-start").classList.toggle("is-running", !!running);
    $("pr-restart").classList.toggle("hidden", !(running || paused));
  }

  async _primary() {
    const ps = this.ps;
    if (ps && ps.running) return this._onState(await this.api("/api/practice/pause", { reason: "user" }));
    if (ps && ps.paused && ps.pause_reason === "stopped" && ps.stop_beat !== null) {
      return this._onState(await this.api("/api/practice/seek", { beat: ps.stop_beat, run: ps.run }));
    }
    if (ps && ps.paused) return this._onState(await this.api("/api/practice/resume", {}));
    return this.start();
  }

  async start() {
    if (!this.song) return;
    // Sound starts in this click. Do not wait long: without a click (checks) it never starts.
    if (!this.piano.started && this.startSound) {
      await Promise.race([this.startSound().catch(() => {}), new Promise((r) => setTimeout(r, 300))]);
    }
    this._hideEnd();
    const o = this.opts;
    // Skill moments (PLAN 8.2): only in Play mode, for the hands that the user plays.
    const [rs, re] = this._range();
    const moments = o.mode === "wait"
      ? this.moments.filter((m) => !m.done && m.hands.every((h) => o.hands.includes(h)) && m.at_beat < re - 1e-6
        && m.at_beat >= rs - 1e-6) : [];
    const first = moments.find((m) => m.at_beat <= rs + 1e-6);
    if (first) { // the new skill is at the start: teach it before the song starts
      this._showSkill(first.id, first.at_beat, true);
      return;
    }
    try {
      const s = await this.api("/api/practice/start", {
        song_id: this.song.id, mode: o.mode, hands: o.hands, speed: o.speed, section: o.section,
        count_in: o.countIn, accompany: o.accompany, output: o.kbSound ? "keyboard" : "mac",
        breaks: moments.map((m) => ({ beat: m.at_beat, skill: m.id })),
        ...(o.loop === false && (o.section !== null || o.span) ? { loop: false } : {}),
        ...(o.span ? { span: o.span, section: null } : {}),
      });
      this.results = new Map();
      this.peek = null;
      this._onState(s); // a new run: _onState sets the sound schedule from its anchor
    } catch (err) {
      this._say(err.message, 4000);
    }
  }

  _pauseHidden(reason) {
    const ps = this.ps;
    if (!ps || !ps.running) return;
    const body = { reason, run: ps.run }; // the server ignores it if a new run started meanwhile
    if (this.lastBeat !== null) body.at_beat = this.lastBeat;
    this.api("/api/practice/pause", body).then((s) => this._onState(s)).catch(() => {});
  }

  // ------------------------------------------------------------------ backend events

  _onState(s) {
    if (!s || s.type !== "practice") return;
    if (s.song_id === null) {
      if (this.ps && s.seq < this.ps.seq) return; // an old stop (a new song started after it)
      if (this.ps) { this.ps = null; this.piano.releaseAll(); this._applyView(); this._renderControls(); }
      return;
    }
    if (!this.song || s.song_id !== this.song.id) return;
    if (this.ps && s.seq < this.ps.seq && s.song_id === this.ps.song_id) return; // older message
    const prev = this.ps;
    this.ps = s;
    if (s.mode === "play" && (!prev || prev.run !== s.run || prev.passes !== s.passes)) {
      // The backend numbers the notes of the run (active hands, in the range) in start order.
      const hs = new Set(s.hands);
      this.playIds = this.song.notes.filter((n) => hs.has(n.hand) && n.start >= s.range[0] - 1e-6 && n.start < s.range[1] - 1e-6)
        .sort((a, b) => a.start - b.start || a.pitch - b.pitch).map((n) => n.id);
      this.results = new Map();
    }
    this.fallbackOffset = s.t - performance.now() / 1000;
    const beat = this._beatOf(s);
    if (!s.running) this.piano.releaseAll();
    // A new run, a loop pass, a jump back, a pause: schedule the sound again from the anchor. The
    // anchor (not "now") is the start: the first note and click of a part are exactly at the anchor.
    if (!prev || !this.sched || !s.running || prev.run !== s.run || prev.passes !== s.passes
        || beat < this.sched.beat - 0.01) {
      this._resetAudio(s.running ? Math.max(Math.min(beat, s.anchor_beat), beat - LATE_MAX_S * s.rate) : beat);
    }
    this._applyView();
    this._renderControls();
  }

  _onWrong(e) {
    this._mark("wrong", e.pitch);
    this.renderer.flashWrong(e.pitch);
    if (this.ps && this.ps.mode === "play") return; // play-along: the key is red; the tips come from the backend
    const exp = this._expectedText((e.expected || []).map((p) => ({ pitch: p })));
    this._say(`Not this key. ${exp}`, 1800);
  }

  // One pass of a repeated part (play-along Loop): the points, and the automatic speed step.
  _onPass(e) {
    const sc = e.score;
    let text = `Run ${e.pass}: ${sc.total} points. ${"★".repeat(sc.stars)}`;
    if (e.adapt) {
      text = `${text} ${this.terms ? this.terms.plainText(e.adapt.text) : e.adapt.text}`;
      this.opts.speed = e.adapt.speed;
      this._renderControls();
    }
    this._say(text, 4000, e.adapt ? "go" : "");
  }

  _onEnd(e) {
    if (!this.song || e.song_id !== this.song.id) return;
    $("pr-findings").classList.add("hidden");
    $("pr-findings").innerHTML = "";
    $("pr-end-adapt").classList.add("hidden");
    $("pr-end-score").classList.toggle("hidden", e.mode !== "play");
    $("pr-end-card").classList.toggle("is-play", e.mode === "play");
    this.lastEnd = e;
    if (e.mode === "play") return this._onPlayEnd(e);
    const wait = e.mode === "wait";
    $("pr-end-title").textContent = wait ? "Well done! You played the whole song." : "This is the end of the song.";
    $("pr-end-text").textContent = wait
      ? (e.accuracy !== undefined
        ? `You pressed ${Math.round(e.accuracy)}% of the keys right the first time. Wrong keys: ${e.wrong}.`
        : (e.wrong === 0 ? "You pressed no wrong keys." : `Wrong keys: ${e.wrong}. Play it again to make it better.`))
      : "Now play it yourself. The song waits for you at each key.";
    $("pr-end-goal").textContent = "";
    $("pr-end-goal").className = "pr-end-goal";
    $("pr-end-again").classList.toggle("hidden", !wait);
    $("pr-end-play").classList.toggle("hidden", wait);
    $("pr-end").classList.remove("hidden");
    $("pr-start").classList.remove("primary"); // one primary action: the end card's button
    const btn = wait ? $("pr-end-again") : $("pr-end-play");
    btn.focus({ preventScroll: true }); // keyboard users: the focus goes to the card
    if (wait) this.celebrate($("pr-end-title"));
  }

  _onPlayEnd(e) {
    const sc = e.score;
    this.banner.until = 0; // an old tip does not stay after the end
    $("pr-end-title").textContent = sc.stars === 3 ? "Great playing!" : sc.stars === 2 ? "Good run!" : "You played to the end!";
    $("pr-score-stars").textContent = "★".repeat(sc.stars) + "☆".repeat(3 - sc.stars);
    $("pr-score-stars").setAttribute("aria-label", `${sc.stars} of 3 stars`);
    $("pr-score-total").textContent = String(sc.total);
    $("pr-score-acc").textContent = `${Math.round(sc.accuracy)}%`;
    $("pr-score-time").textContent = `${Math.round(sc.timing)}%`;
    $("pr-score-len").textContent = `${Math.round(sc.length)}%`;
    $("pr-end-text").textContent = `You played ${sc.hit} of ${sc.notes} keys. ${sc.perfect + sc.good} were on time.`;
    $("pr-end-goal").textContent = "";
    $("pr-end-goal").className = "pr-end-goal";
    $("pr-end-again").classList.remove("hidden");
    $("pr-end-play").classList.add("hidden");
    $("pr-end").classList.remove("hidden");
    $("pr-start").classList.remove("primary");
    $("pr-end-again").focus({ preventScroll: true });
    if (sc.stars === 3) this.celebrate($("pr-end-title"));
  }

  // The course result for this run (event "course"): is the song done, and what is still needed?
  _onResult(r) {
    this.lastResult = r;
    const el = $("pr-end-goal");
    let text = "";
    let kind = "";
    if (r.newly_done) { text = "This song is done! It is marked in the course."; kind = "ok"; }
    else if (r.done) { text = "This song is done."; kind = "ok"; }
    else if (r.ladder) {
      const need = [];
      if (!r.full) need.push("play the whole song");
      if ((r.speed || 0) < r.rule.speed / 100 - 1e-6) need.push(`play at ${r.rule.speed}% speed`);
      if (!(r.required_hands || []).every((h) => (r.hands || []).includes(h))) {
        need.push(r.required_hands.length > 1 ? "play with both hands" : r.required_hands[0] === "L" ? "play with the left hand" : "play with the right hand");
      }
      if (r.mode === "play") {
        if ((r.score ? r.score.total : 0) < r.rule.score) need.push(`get ${r.rule.score} points or more`);
      } else if (!r.wait_counts) {
        need.length = 0;
        need.push(r.keys_ok ? "now play along with the song (select \"Play along\")"
          : `press ${r.rule.score}% of the keys right the first time, then play along with the song`);
      } else if ((r.accuracy || 0) < r.rule.score) need.push(`press ${r.rule.score}% of the keys right the first time`);
      if (need.length) text = `To finish this song: ${need.join(", ")}.`;
    }
    el.textContent = text;
    el.className = `pr-end-goal ${kind}`;
    if (r.newly_done) this.celebrate($("pr-end-title"));
    if (r.mode === "play") this._showAfterRun(r);
  }

  // ------------------------------------------------------------------ after a play-along run (PLAN 7.2, 7.3)

  _showAfterRun(r) {
    const words = (t) => (this.terms ? this.terms.markup(t) : esc(t));
    const ad = r.adapt;
    this.adapt = ad || null;
    const box = $("pr-end-adapt");
    $("pr-end-adapt-text").textContent = "";
    if (ad) {
      const parts = [];
      if (ad.learned_text) parts.push(ad.learned_text);
      if (ad.text) parts.push(ad.text);
      $("pr-end-adapt-text").innerHTML = parts.map(words).join(" ");
      const next = $("pr-end-next");
      next.classList.toggle("hidden", ad.action !== "next");
      if (ad.action === "next") {
        next.textContent = { both: "Play with both hands", part: "Play the next part", whole: "Play the whole song",
          song: "Select a new song" }[ad.next.id];
      }
      if (ad.action === "slower" || ad.action === "faster") {
        this.opts.speed = ad.speed;
        this._renderControls();
      }
      box.classList.remove("hidden");
    }
    this.findings = r.findings || [];
    const list = $("pr-findings");
    list.innerHTML = "";
    if (!this.findings.length) {
      list.classList.add("hidden");
      return;
    }
    this.findings.forEach((f, i) => {
      const card = document.createElement("div");
      card.className = "pr-finding";
      card.dataset.i = String(i);
      card.innerHTML = `<div class="pr-finding-num">${i + 1}</div>
        <div class="pr-finding-body${f.place ? " has-preview" : ""}"><p class="pr-finding-text">${words(f.text)}</p>
        ${f.place ? `<canvas class="pr-preview" role="img" aria-label="A small picture of this place. Red notes are the keys to practice."></canvas>` : ""}
        <div class="pr-finding-buttons">
          ${f.place ? `<button class="btn btn-sm" data-act="show" data-i="${i}">Show me</button>` : ""}
          ${f.action ? `<button class="btn btn-sm${i === 0 ? " primary" : ""}" data-act="do" data-i="${i}">${esc(f.action.label)}</button>` : ""}
        </div></div>`;
      list.appendChild(card);
    });
    list.classList.remove("hidden");
    // Previews (wrong notes red), and Rule 1: the first place is shown on the falling notes.
    this.previews = this.findings.map((f, i) => {
      if (!f.place) return null;
      const c = list.querySelector(`.pr-finding[data-i="${i}"] canvas`);
      const v = new PreviewView(c, { song: this.song, place: f.place, hands: (this.lastEnd || {}).hands || this.opts.hands,
        log: (this.lastEnd || {}).log, colors: { ...this.colors, keyWhite: cssVar("--white-key") } });
      v.draw(); // at once (the card is in the page now), and again after the next layout
      requestAnimationFrame(() => v.draw());
      return v;
    });
    const first = this.findings.findIndex((f) => f.place);
    if (first >= 0) this._focusFinding(first);
  }

  _focusFinding(i) {
    const f = this.findings && this.findings[i];
    if (!f || !f.place) return;
    this.place = f.place;
    this.peek = Math.max(0, f.place.start - 0.25);
    for (const c of document.querySelectorAll(".pr-finding")) c.classList.toggle("is-shown", Number(c.dataset.i) === i);
    this._applyView();
  }

  // "Show me": the app plays that place (Mac sound) and a line moves through the preview.
  async _showMe(i) {
    const f = this.findings[i];
    const v = this.previews[i];
    if (!f || !f.place || !v) return;
    this._focusFinding(i);
    if (!this.piano.started && this.startSound) await this.startSound().catch(() => {});
    const rate = (this.song.bpm * Math.min(1, this.opts.speed)) / 60;
    const now = this.piano.audioNow();
    const hands = new Set(v.hands);
    for (const n of this.song.notes) {
      if (n.start < f.place.start - 1e-6 || n.start >= f.place.end - 1e-6 || !hands.has(n.hand)) continue;
      this.piano.playAt(n.pitch, now + 0.05 + (n.start - f.place.start) / rate, (n.dur / rate) * 0.95, n.vel || 80);
    }
    const t0 = performance.now() + 50;
    const total = ((f.place.end - f.place.start) / rate) * 1000;
    const id = (this._showId = (this._showId || 0) + 1);
    const step = () => {
      if (id !== this._showId) return;
      const k = Math.min(1, Math.max(0, (performance.now() - t0) / total));
      v.playBeat = f.place.start + k * (f.place.end - f.place.start);
      this.peek = v.playBeat - 0.25;
      v.draw();
      if (k < 1) requestAnimationFrame(step);
      else { v.playBeat = null; v.draw(); }
    };
    requestAnimationFrame(step);
  }

  _findingButton(i, act) {
    if (act === "show") return this._showMe(i);
    const f = this.findings[i];
    if (!f || !f.action) return;
    const a = f.action;
    const o = this.opts;
    o.loop = null;
    // An action with a place loops that place. An action with no place (slower, the click, one
    // hand, both hands) keeps the current part or place.
    if (a.span) { o.section = null; o.span = a.span; }
    if (a.mode) o.mode = a.mode;
    if (a.hands) o.hands = a.hands.filter((h) => this.handsPresent.includes(h));
    if (typeof a.speed === "number") o.speed = a.speed;
    if (a.id === "click") o.click = true;
    if (a.id === "both_half" && o.hands.length < 2) o.hands = [...this.handsPresent];
    $("pr-part").value = o.section === null ? "" : String(o.section);
    if (a.span) this.place = { start: a.span[0], end: a.span[1] };
    else if (!o.span) this.place = null;
    this._saveOptions();
    this._renderControls();
    this._restartWith();
  }

  async _nextStep() {
    const ad = this.adapt;
    if (!ad || ad.action !== "next") return;
    const n = ad.next;
    if (n.id === "song") return this.onReturn(this.returnTo);
    if (n.hands) this.opts.hands = n.hands.filter((h) => this.handsPresent.includes(h));
    if (n.id === "part" || n.id === "whole") { this.opts.section = n.section; this.opts.span = null; }
    $("pr-part").value = this.opts.section === null ? "" : String(this.opts.section);
    this._renderControls();
    this._restartWith();
  }

  async _restartWith() {
    this._hideEnd();
    if (this.ps && this.ps.song_id) {
      try { this._onState(await this.api("/api/practice/stop", {})); } catch { /* start shows it */ }
    }
    this._applyView();
    this.start();
  }

  // ------------------------------------------------------------------ skill moments (PLAN 8.2)

  _showSkill(skillId, atBeat, beforeStart = false) {
    const m = this.moments.find((x) => x.id === skillId);
    if (!m) return;
    const sk = m.skill;
    this.skill = { m, atBeat, beforeStart, passed: false };
    $("pr-skill-name").innerHTML = `New: ${this.terms ? this.terms.markup(sk.name) : esc(sk.name)}`;
    $("pr-skill-text").innerHTML = sk.text.map((t) => `<p>${this.terms ? this.terms.markup(t) : esc(t)}</p>`).join("");
    const pitches = sk.demo.notes.map((n) => n.pitch);
    const beats = [...new Set(sk.demo.notes.map((n) => n.start))].sort((a, b) => a - b);
    $("pr-skill").classList.remove("hidden");
    this.skillPanel.setup({ pitches, positions: sk.demo.hand_positions, stepBeats: beats });
    this._skillButtons("demo");
    this.piano.releaseAll();
  }

  _skillButtons(stage) {
    $("pr-skill-demo").classList.toggle("primary", stage === "demo");
    $("pr-skill-try").classList.toggle("primary", stage === "try");
    $("pr-skill-try").classList.toggle("hidden", stage === "done");
    $("pr-skill-demo").classList.toggle("hidden", stage === "done");
    $("pr-skill-go").classList.toggle("hidden", stage !== "done");
    $("pr-skill-skip").classList.toggle("hidden", stage === "done");
    $("pr-skill-go").textContent = this.skill && this.skill.beforeStart ? "Start the song" : "Continue the song";
    const focus = stage === "done" ? $("pr-skill-go") : stage === "try" ? $("pr-skill-try") : $("pr-skill-demo");
    focus.focus({ preventScroll: true });
  }

  async _skillDemo() {
    if (!this.skill) return;
    this.skillPanel.stop();
    await this.skillPanel.demo(this.skill.m.skill.demo);
    if (this.skill && !this.skill.passed) this._skillButtons("try");
  }

  async _skillTry() {
    if (!this.skill) return;
    this.skillPanel.stopDemo();
    const id = this.skill.m.id;
    $("pr-skill-try").textContent = "Start again";
    try {
      await this.skillPanel.start({ source: "skill", ref: id }, {
        onPass: async (st) => {
          if (!this.skill || this.skill.m.id !== id) return;
          this.skill.passed = true;
          this.skill.m.done = true;
          this.celebrate($("pr-skill-name"));
          this._skillButtons("done");
          const unlocked = (st.result && st.result.unlocked) || [];
          if (unlocked.length && this.terms) {
            await this.terms.load();
            this.refreshWords();
            await this.terms.firstUse(unlocked);
          }
        },
      });
    } catch (err) {
      this._say(err.message, 4000);
    }
  }

  async _skillContinue(passed) {
    const sk = this.skill;
    if (!sk) return;
    this.skillPanel.stop();
    this.skillPanel.stopDemo();
    if (!passed) sk.m.done = true; // "Skip": no stop for this skill in this visit (it stays not done)
    this._hideSkill();
    if (sk.beforeStart || !this.ps || !this.ps.paused) return this.start();
    try {
      this._onState(await this.api("/api/practice/seek", { beat: sk.m.resume_beat, run: this.ps.run }));
    } catch (err) {
      this._say(err.message, 4000);
    }
  }

  _hideSkill() {
    this.skill = null;
    $("pr-skill").classList.add("hidden");
    $("pr-skill-try").textContent = "Try it 3 times";
    if (this.skillPanel) { this.skillPanel.stop(); this.skillPanel.stopDemo(); }
  }

  _hideEnd() {
    $("pr-end").classList.add("hidden");
    $("pr-start").classList.add("primary");
    this._showId = (this._showId || 0) + 1;
  }

  _mark(kind, pitch) {
    for (const k of Object.keys(this.marks)) {
      if (k === kind) continue;
      this.marks[k].delete(pitch);
      this.kb.mark(pitch, k, false);
    }
    this.marks[kind].set(pitch, performance.now());
    this.kb.mark(pitch, kind, true);
    if (!this.down.has(pitch)) this._unmarkLater(kind, pitch);
  }

  _unmarkLater(kind, pitch) {
    const t0 = this.marks[kind].get(pitch);
    if (t0 === undefined) return;
    const wait = Math.max(0, MARK_MIN_MS - (performance.now() - t0));
    setTimeout(() => {
      if (this.marks[kind].get(pitch) === t0 && !this.down.has(pitch)) {
        this.marks[kind].delete(pitch);
        this.kb.mark(pitch, kind, false);
      }
    }, wait);
  }

  // ------------------------------------------------------------------ clock

  _serverNow() {
    const t = this.link.serverNow();
    return t === null ? performance.now() / 1000 + this.fallbackOffset : t;
  }

  _beatOf(s, now = this._serverNow()) {
    let b = s.running ? s.anchor_beat + (now - s.anchor_t) * s.rate : s.anchor_beat;
    if (s.mode === "wait" && s.hold_beat !== null && s.hold_beat !== undefined) b = Math.min(b, s.hold_beat);
    return Math.min(b, s.range[1]);
  }

  _range() {
    const o = this.opts;
    if (o.span) return [o.span[0], Math.min(o.span[1], this.song.end)];
    if (o.section !== null && this.song.sections[o.section]) {
      const s = this.song.sections[o.section];
      return [s.start, Math.min(s.end, this.song.end)];
    }
    return [0, this.song.end];
  }

  _beat() {
    // After a run, the view can show the place of a finding (PLAN 7.4 Rule 1).
    if (this.peek !== null && (!this.ps || this.ps.done)) return this.peek;
    if (this.ps) return this._beatOf(this.ps);
    const [start] = this._range();
    return start - (this.opts.countIn ? this.song.time_signature[0] : 0);
  }

  // What the renderer shows: active hands, wait stops, the repeated part.
  _applyView() {
    if (!this.song) return;
    const ps = this.ps;
    const mode = ps ? ps.mode : this.opts.mode;
    const hands = new Set(ps ? ps.hands : this.opts.hands);
    const range = ps ? ps.range : this._range();
    let stopBeats = null;
    if (mode === "wait") {
      const set = new Set();
      for (const n of this.song.notes) {
        if (hands.has(n.hand) && n.start >= range[0] - 1e-6 && n.start < range[1] - 1e-6) set.add(n.start);
      }
      stopBeats = [...set].sort((a, b) => a - b);
    }
    this.view = { mode, hands, range };
    this.renderer.setView({
      active: hands, stopBeats, stopIndex: ps ? ps.stop_index || 0 : 0, waiting: !!(ps && ps.waiting),
      range, loop: ps ? ps.loop : this.opts.section !== null || !!this.opts.span, countInTo: range[0],
      place: this.place && (!ps || ps.done || !ps.loop) ? this.place : null,
      stopBeat: ps && ps.paused && ps.pause_reason === "stopped" ? ps.stop_beat : null,
      results: mode === "play" ? this.results : null,
    });
    // Notes that the app plays (Mac sound and key glow): watch = all; wait = the other hand.
    const accompany = ps ? ps.accompany : this.opts.accompany;
    this.appNotes = this.song.notes
      .filter((n) => (mode === "watch" || (accompany && !hands.has(n.hand)))
        && n.start >= range[0] - 1e-6 && n.start < range[1] - 1e-6)
      .sort((a, b) => a.start - b.start);
  }

  // ------------------------------------------------------------------ Mac sound: app notes and the click

  // Sound is scheduled from sched.beat (notes) and sched.click (the next click) up to "now + ahead".
  _resetAudio(beat = this._beat()) {
    this.sched = { beat, click: Math.ceil(beat - 1e-6) };
  }

  _schedule(beat) {
    const ps = this.ps;
    if (!ps || !ps.running || !this.piano.running) return;
    if (!this.sched) this._resetAudio(beat);
    const rate = ps.rate;
    const now = this.piano.audioNow();
    const hold = ps.mode === "wait" ? ps.hold_beat : null;
    const horizon = beat + AUDIO_AHEAD_S * rate;
    // Notes: start in [sched.beat, horizon). In wait mode, notes at the stop wait for the user.
    const noteLimit = hold === null || hold === undefined ? horizon : Math.min(horizon, hold - 1e-6);
    if (ps.output !== "keyboard" && noteLimit > this.sched.beat) {
      const notes = this.appNotes;
      for (let i = lowerBound(notes, this.sched.beat - 1e-6, (n) => n.start); i < notes.length; i++) {
        const n = notes[i];
        if (n.start >= noteLimit) break;
        if (n.start < this.sched.beat - 1e-6) continue;
        const when = now + Math.max(0, (n.start - beat) / rate);
        this.piano.playAt(n.pitch, when, (n.dur / rate) * 0.95, n.vel || 80);
      }
      this.sched.beat = noteLimit;
    } else if (noteLimit > this.sched.beat) {
      this.sched.beat = noteLimit;
    }
    // The click: count-in clicks always (if on); song clicks if "The click" is on.
    const clickLimit = hold === null || hold === undefined ? horizon : Math.min(horizon, hold + 1e-6);
    const [start] = ps.range;
    const group = this.song.time_signature[0];
    while (this.sched.click < clickLimit) {
      const k = this.sched.click;
      const inCountIn = k < start - 1e-6 || (ps.lead_to !== null && ps.lead_to !== undefined && k < ps.lead_to - 1e-6
        && k >= ps.lead_to - this.song.time_signature[0] - 1e-6); // the clicks before "Continue from here"
      if ((inCountIn && ps.count_in > 0) || (!inCountIn && this.opts.click)) {
        const accent = ((((k - start) % group) + group) % group) === 0;
        this.piano.clickAt(now + Math.max(0, (k - beat) / rate), accent);
      }
      this.sched.click += 1;
    }
  }

  // ------------------------------------------------------------------ frame

  _frame(ts, id) {
    if (!this.visible || id !== this._loop) return;
    requestAnimationFrame((t) => this._frame(t, id));
    if (!this.song) return;
    const ps = this.ps;
    if (this.lastFrame !== null) {
      const dt = ts - this.lastFrame;
      this.frameTimes.push(dt);
      if (this.frameTimes.length > 1200) this.frameTimes.shift();
      if (ps && ps.running && dt > GAP_PAUSE_MS) this._pauseHidden("hidden"); // no frames: window hidden
    }
    this.lastFrame = ts;
    this._render();
  }

  // Draw one frame now (also used by checks when the window gets no animation frames).
  drawOnce() {
    if (this.song && this.visible) this._render();
  }

  _render() {
    const t0 = performance.now();
    const beat = this._beat();
    const rm = this.reducedMotion.matches;
    this.renderer.draw(beat, rm);
    const hint = this._drawHands(beat, rm);
    this._keys(beat);
    this._schedule(beat);
    this._updateBanner(beat, hint);
    this._progress(beat);
    this.lastBeat = beat;
    this.drawTimes.push(performance.now() - t0);
    if (this.drawTimes.length > 1200) this.drawTimes.shift();
  }

  _drawHands(beat, rm) {
    const list = [];
    for (const h of this.handsPresent) {
      const { pos, next } = positionAt(this.positions[h], beat);
      list.push({ hand: h, pos, next, active: this.view.hands.has(h), nextFinger: this._nextFinger(h, beat) });
    }
    return this.hands.draw(list, beat, this.colors, rm);
  }

  _nextFinger(hand, beat) {
    const notes = this.handNotes[hand];
    for (let i = lowerBound(notes, beat - 8, (n) => n.start); i < notes.length; i++) {
      const n = notes[i];
      if (n.start + n.dur <= beat + 1e-6 && n.start < beat - 1e-6) continue; // over
      if (n.start - beat > 1) return 0;
      return n.finger || 0;
    }
    return 0;
  }

  _keys(beat) {
    // Keys that the app plays now glow in the hand color.
    const play = { R: [], L: [] };
    const notes = this.appNotes || [];
    if (this.ps && (this.ps.running || this.ps.paused)) {
      for (let i = lowerBound(notes, beat - this.renderer.maxDur, (n) => n.start); i < notes.length; i++) {
        const n = notes[i];
        if (n.start > beat + 1e-6) break;
        if (beat < n.start + n.dur - 0.02) play[n.hand].push(n.pitch);
      }
    }
    this.kb.setMarked("play-R", play.R);
    this.kb.setMarked("play-L", play.L);
    // The keys to press now (wait mode).
    const target = { R: [], L: [] };
    if (this.ps && this.ps.waiting) for (const e of this.ps.expected) target[e.hand].push(e.pitch);
    this.kb.setMarked("target-R", target.R);
    this.kb.setMarked("target-L", target.L);
  }

  _expectedText(expected) {
    const byHand = { R: [], L: [] };
    const notes = this.ps ? this.ps.expected : [];
    for (const e of expected) {
      const full = notes.find((x) => x.pitch === e.pitch) || e;
      byHand[full.hand || "R"].push(full);
    }
    const part = (list) => list.map((e) => (e.finger ? `${keyName(e.pitch)} with finger ${e.finger}` : keyName(e.pitch))).join(" and ");
    const r = byHand.R.length ? part(byHand.R) : "";
    const l = byHand.L.length ? part(byHand.L) : "";
    if (r && l) return `Right hand: press ${r}. Left hand: press ${l}.`;
    const one = r || l;
    const together = (byHand.R.length + byHand.L.length) > 1 ? " together" : "";
    return `Press ${one}${together}.`;
  }

  _say(text, ms, kind = "") {
    this.banner = { text, until: performance.now() + ms, kind };
  }

  _updateBanner(beat, hint) {
    const ps = this.ps;
    const st = this.getStatus();
    const mode = ps ? ps.mode : this.opts.mode;
    let text;
    let kind = "";
    if (performance.now() < this.banner.until) {
      text = this.banner.text;
      kind = this.banner.kind || (text.startsWith("Not this key") ? "bad" : "");
    } else if (mode === "wait" && !st.connected) {
      text = "Connect your keyboard to play. You can select Watch to listen to the song.";
      kind = "warn";
    } else if (ps && ps.paused) {
      text = ps.pause_reason === "skill"
        ? "The song stopped for a new skill."
        : ps.pause_reason === "stopped"
        ? "You stopped. Continue from here? The dashed line shows the place. Click \"Continue from here\"."
        : ps.pause_reason === "hidden"
        ? "The song stopped because the window was not in front. Click Continue."
        : ps.pause_reason === "left"
          ? "The song stopped because you went to a different page. Click Continue."
          : "The song is paused. Click Continue.";
    } else if (ps && ps.running && beat < ps.range[0] - 1e-6) {
      text = "Get ready. The song starts after the count.";
    } else if (hint && ps && ps.running) {
      text = hint;
      kind = "move";
    } else if (ps && ps.waiting) {
      text = this._expectedText(ps.expected);
      kind = "go";
    } else if (ps && ps.running) {
      text = mode === "wait" ? "Press each key when its note touches the line."
        : mode === "play" ? "Press each key when its note touches the line. The song does not wait." : "Watch and listen. The app plays the song.";
    } else if (ps && ps.done) {
      text = "The song is at the end.";
    } else {
      text = mode === "wait" ? "Click \"Start playing\". The song waits for you at each key."
        : mode === "play" ? "Click \"Start playing along\". The song goes on at its speed. You get points for each key."
        : "Click \"Start watching\". The app plays the song for you.";
    }
    if (text !== this._bannerText || kind !== this._bannerKind) {
      this._bannerText = text;
      this._bannerKind = kind;
      const el = $("pr-banner");
      el.textContent = text;
      el.className = `pr-banner ${kind}`;
    }
  }

  _progress(beat) {
    const [a, b] = this.view.range;
    const f = Math.max(0, Math.min(1, (beat - a) / (b - a)));
    const pct = Math.round(f * 1000) / 10;
    if (pct !== this._pct) {
      this._pct = pct;
      $("pr-progress-fill").style.width = `${pct}%`;
    }
  }

  // ------------------------------------------------------------------ theme and size

  _readColors() {
    this.colors = {
      R: cssVar("--hand-right"), L: cssVar("--hand-left"),
      on: { R: cssVar("--on-hand-right"), L: cssVar("--on-hand-left") }, dotEdge: cssVar("--dot-edge"),
      bg: cssVar("--stage-bg"), lane: cssVar("--stage-lane"), grid: cssVar("--stage-grid"),
      middleC: cssVar("--stage-middle-c"), line: cssVar("--accent"), bad: cssVar("--bad"),
      text: cssVar("--text"), band: cssVar("--stage-band"), bandEdge: cssVar("--accent"),
      waitRing: cssVar("--text"), barLine: cssVar("--stage-bar"),
      placeBand: cssVar("--place-band"), placeEdge: cssVar("--place-edge"),
    };
    this.renderer.setColors(this.colors);
  }

  _resize() {
    if (!this.visible) return;
    this.renderer.resize();
    this.hands.resize();
  }

  // ------------------------------------------------------------------ checks (frame rate)

  resetStats() {
    this.frameTimes = [];
    this.drawTimes = [];
  }

  stats() {
    const med = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : null; };
    const p95 = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.round(0.95 * (s.length - 1)))] : null; };
    const period = 1000 / 60;
    let missed = 0;
    for (const dt of this.frameTimes) missed += Math.max(0, Math.round(dt / period) - 1);
    const n = this.frameTimes.length;
    return {
      frames: n, frame_median_ms: med(this.frameTimes), frame_p95_ms: p95(this.frameTimes),
      frame_max_ms: n ? Math.max(...this.frameTimes) : null,
      dropped_pct: n ? (100 * missed) / (n + missed) : null,
      draw_median_ms: med(this.drawTimes), draw_p95_ms: p95(this.drawTimes),
    };
  }
}
