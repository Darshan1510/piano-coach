// Practice screen: falling notes, hand outline, watch mode and wait mode (PLAN 6.3-6.5).
//
// The backend owns the song clock (riyaz/practice.py). Each "practice" event has an anchor:
//   beat = anchor_beat + (server_now - anchor_t) * rate      (clamped at hold_beat in wait mode)
// server_now comes from the clock offset in ws.js (ping/pong, median of 5).
// This module draws that beat at 60 fps and plays the app's notes and the click on the Mac.
//
// Words (PLAN 7.4, Level 1-2): "speed" (not tempo), "the click" (not beat), "Part 1" (not bar),
// "pause", "keys together". No bar lines before Level 3.

import { Keyboard, keyLayout, keyName } from "/static/js/keyboard.js";
import { FallingNotes } from "/static/js/renderer.js";
import { HandsView, positionAt, positionsOf } from "/static/js/hands.js";
import { handsText } from "/static/js/songs.js";

const $ = (id) => document.getElementById(id);
const HAND = { R: "right hand", L: "left hand" };
const LOW = 36;
const HIGH = 96;
const AUDIO_AHEAD_S = 0.15; // schedule Mac notes and clicks this far ahead
const GAP_PAUSE_MS = 1000; // no frame for this long while the song runs = the window was hidden
const MARK_MIN_MS = 250; // a red or green key stays at least this long
const LATE_MAX_S = 0.25; // after a new anchor, a note or click this late still plays (at once)

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
  constructor({ link, piano, api, celebrate, reducedMotion, getStatus, startSound }) {
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
      accompany: true, kbSound: false };
    this.marks = { wrong: new Map(), hit: new Map() }; // pitch -> time when set
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

  async open(songId) {
    const song = await this.api(`/api/songs/${encodeURIComponent(songId)}`);
    if (this.ps && this.ps.song_id && this.ps.song_id !== song.id) {
      await this.api("/api/practice/stop", {}).catch(() => {});
    }
    this.song = song;
    this.ps = null;
    this.handsPresent = ["R", "L"].filter((h) => song.notes.some((n) => n.hand === h));
    this.opts.hands = this.handsPresent.includes("R") ? ["R"] : [this.handsPresent[0]];
    this.opts.section = null;
    this.renderer.setSong(song);
    this.positions = { R: positionsOf(song, "R"), L: positionsOf(song, "L") };
    this.handNotes = {
      R: song.notes.filter((n) => n.hand === "R").sort((a, b) => a.start - b.start),
      L: song.notes.filter((n) => n.hand === "L").sort((a, b) => a.start - b.start),
    };
    $("pr-title").textContent = song.title;
    $("pr-level").textContent = `Level ${song.level}`;
    $("pr-hands-text").textContent = handsText(this.handsPresent);
    $("pr-credit").textContent = song.credit || "";
    // Parts (song sections) for "Repeat a part".
    const sel = $("pr-part");
    sel.innerHTML = "";
    sel.appendChild(new Option("All the song", ""));
    song.sections.forEach((s, i) => sel.appendChild(new Option(`Repeat ${s.name}`, String(i))));
    sel.value = "";
    const clicks = song.time_signature[0];
    $("pr-countin-label").textContent = `${clicks} clicks before the start`;
    this._hideEnd();
    this._renderControls();
    this._applyView();
    const st = await this.api("/api/practice").catch(() => null);
    if (st && st.song_id === song.id) this._onState(st);
    return song;
  }

  show() {
    this.visible = true;
    this._resize();
    this._renderControls();
    this.lastFrame = null;
    const id = (this._loop = (this._loop || 0) + 1); // one animation loop only (show() can come again)
    requestAnimationFrame((ts) => this._frame(ts, id));
  }

  hide() {
    this.visible = false;
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
    $("pr-part").addEventListener("change", (e) => this._setOpt("section", e.target.value === "" ? null : Number(e.target.value)));
    $("pr-countin").addEventListener("change", (e) => { this._setOpt("countIn", e.target.checked); this._saveOptions(); });
    $("pr-accompany").addEventListener("change", (e) => this._setOpt("accompany", e.target.checked));
    $("pr-kbsound").addEventListener("change", (e) => this._setOpt("kbSound", e.target.checked));
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
    for (const group of document.querySelectorAll("#pr-mode, #pr-hands")) radioKeys(group);

    this.link.on("practice", (s) => this._onState(s));
    this.link.on("practice_wrong", (e) => { if (this._ours(e)) this._onWrong(e); });
    this.link.on("practice_hit", (e) => { if (this._ours(e)) this._mark("hit", e.pitch); });
    this.link.on("practice_end", (e) => this._onEnd(e));
    this.link.on("note_on", (e) => { this.down.add(e.pitch); this.kb.setDown(e.pitch, true); });
    this.link.on("note_off", (e) => {
      this.down.delete(e.pitch);
      this.kb.setDown(e.pitch, false);
      for (const kind of ["wrong", "hit"]) this._unmarkLater(kind, e.pitch);
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
      this._renderControls();
      this._applyView();
    } catch { /* keep the defaults */ }
  }

  _saveOptions() {
    const o = this.opts;
    this.api("/api/settings/practice", { speed: o.speed, click: o.click, count_in: o.countIn }).catch(() => {});
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
    $("pr-accompany-row").classList.toggle("hidden", !other || o.mode !== "wait");
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
    $("pr-start-text").textContent = running ? "Pause" : paused ? "Continue" : o.mode === "wait" ? "Start playing" : "Start watching";
    $("pr-start").classList.toggle("is-running", !!running);
    $("pr-restart").classList.toggle("hidden", !(running || paused));
  }

  async _primary() {
    const ps = this.ps;
    if (ps && ps.running) return this._onState(await this.api("/api/practice/pause", { reason: "user" }));
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
    try {
      const s = await this.api("/api/practice/start", {
        song_id: this.song.id, mode: o.mode, hands: o.hands, speed: o.speed, section: o.section,
        count_in: o.countIn, accompany: o.accompany, output: o.kbSound ? "keyboard" : "mac",
      });
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
    const exp = this._expectedText((e.expected || []).map((p) => ({ pitch: p })));
    this._say(`Not this key. ${exp}`, 1800);
  }

  _onEnd(e) {
    if (!this.song || e.song_id !== this.song.id) return;
    const wait = e.mode === "wait";
    $("pr-end-title").textContent = wait ? "Well done! You played the whole song." : "This is the end of the song.";
    $("pr-end-text").textContent = wait
      ? (e.wrong === 0 ? "You pressed no wrong keys." : `Wrong keys: ${e.wrong}. Play it again to make it better.`)
      : "Now play it yourself. The song waits for you at each key.";
    $("pr-end-again").classList.toggle("hidden", !wait);
    $("pr-end-play").classList.toggle("hidden", wait);
    $("pr-end").classList.remove("hidden");
    $("pr-start").classList.remove("primary"); // one primary action: the end card's button
    const btn = wait ? $("pr-end-again") : $("pr-end-play");
    btn.focus({ preventScroll: true }); // keyboard users: the focus goes to the card
    if (wait) this.celebrate($("pr-end-title"));
  }

  _hideEnd() {
    $("pr-end").classList.add("hidden");
    $("pr-start").classList.add("primary");
  }

  _mark(kind, pitch) {
    const other = kind === "wrong" ? "hit" : "wrong";
    this.marks[other].delete(pitch);
    this.kb.mark(pitch, other === "wrong" ? "wrong" : "hit", false);
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
    if (o.section !== null && this.song.sections[o.section]) {
      const s = this.song.sections[o.section];
      return [s.start, Math.min(s.end, this.song.end)];
    }
    return [0, this.song.end];
  }

  _beat() {
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
      range, loop: ps ? ps.loop : this.opts.section !== null, countInTo: range[0],
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
      const inCountIn = k < start - 1e-6;
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

  _say(text, ms) {
    this.banner = { text, until: performance.now() + ms };
  }

  _updateBanner(beat, hint) {
    const ps = this.ps;
    const st = this.getStatus();
    const mode = ps ? ps.mode : this.opts.mode;
    let text;
    let kind = "";
    if (performance.now() < this.banner.until) {
      text = this.banner.text;
      kind = text.startsWith("Not this key") ? "bad" : "";
    } else if (mode === "wait" && !st.connected) {
      text = "Connect your keyboard to play. You can select Watch to listen to the song.";
      kind = "warn";
    } else if (ps && ps.paused) {
      text = ps.pause_reason === "hidden"
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
      text = mode === "wait" ? "Press each key when its note touches the line." : "Watch and listen. The app plays the song.";
    } else if (ps && ps.done) {
      text = "The song is at the end.";
    } else {
      text = mode === "wait" ? "Click \"Start playing\". The song waits for you at each key." : "Click \"Start watching\". The app plays the song for you.";
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
      waitRing: cssVar("--text"),
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
