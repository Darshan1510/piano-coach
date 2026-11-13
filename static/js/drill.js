// Drill panel: a short key check on the real keyboard (keyboard basics, skill moments, warm-up,
// "Find the key"). The backend (riyaz/drill.py) checks the keys and sends "drill" events; this
// panel shows what to press, the hand outline, the progress and short feedback.

import { Keyboard, keyLayout, keyName } from "/static/js/keyboard.js";
import { HandsView, positionAt } from "/static/js/hands.js";

const HINT_MS = 4000; // "Find the key": after this time, show one key as a hint
const DEMO_BEAT_MS = 650;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function rangeFor(pitches) {
  const ps = pitches.filter((p) => p > 0);
  if (!ps.length) return [48, 72];
  let low = Math.floor((Math.min(...ps) - 2) / 12) * 12;
  let high = Math.max(low + 24, Math.ceil((Math.max(...ps) + 2) / 12) * 12);
  low = Math.max(36, low);
  high = Math.min(96, high);
  return [low, high];
}

const FAIL_TEXT = {
  wrong_key: { many: "Not this key. Start again from the first key.", one: "Not this key. Try again." },
  too_short: { many: "Hold the key down longer. Start again from the first key.", one: "Hold the key down longer. Try again." },
  too_early: { many: "Wait in the pause. Lift your hand, count 1, then press. Start again.", one: "Wait in the pause. Lift your hand, count 1, then press." },
  too_soft: { many: "Press harder for a loud sound.", one: "Press harder for a loud sound." },
  too_loud: { many: "Press more gently for a soft sound.", one: "Press more gently for a soft sound." },
};

export class DrillPanel {
  constructor(el, { link, api, piano, reducedMotion }) {
    this.el = el;
    this.link = link;
    this.api = api;
    this.piano = piano;
    this.reducedMotion = reducedMotion;
    this.run = null;
    this.state = null;
    this.opts = {};
    this.onPass = null;
    this.onState = null;
    el.classList.add("dr");
    el.innerHTML = `
      <div class="dr-top"><div class="dr-progress"></div><div class="dr-msg" role="status" aria-live="polite"></div></div>
      <div class="dr-big hidden"></div>
      <div class="dr-kb"><div class="keyboard-wrap pr-keyboard"></div><canvas class="pr-hands-canvas" aria-hidden="true"></canvas></div>`;
    this.$progress = el.querySelector(".dr-progress");
    this.$msg = el.querySelector(".dr-msg");
    this.$big = el.querySelector(".dr-big");
    this.$kbWrap = el.querySelector(".keyboard-wrap");
    this.$canvas = el.querySelector("canvas");
    this.setup({});
    link.on("drill", (s) => { if (this.run !== null && s.run === this.run) this._onState(s); });
    link.on("drill_wrong", (e) => { if (this.run !== null && e.run === this.run) this._onWrong(e); });
    link.on("drill_hit", (e) => { if (this.run !== null && e.run === this.run) this._flash(e.pitch, "hit"); });
    link.on("note_on", (e) => this.kb && this.kb.setDown(e.pitch, true));
    link.on("note_off", (e) => this.kb && this.kb.setDown(e.pitch, false));
    new ResizeObserver(() => this._resize()).observe(this.el);
    new MutationObserver(() => this._draw()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  // opts: {low, high, pitches, positions: [hand positions], stepBeats: [beat of each step], show: "finger",
  //        hintAfterWrong: show the keys to press only after 2 wrong keys}
  setup(opts) {
    this.opts = opts;
    const [low, high] = opts.low ? [opts.low, opts.high] : rangeFor(opts.pitches || [60, 72]);
    if (!this.kb || this.kb.low !== low || this.kb.high !== high) {
      this.$kbWrap.innerHTML = "";
      this.kb = new Keyboard(this.$kbWrap, {
        low, high,
        onPress: (p) => { this.kb.setDown(p, true); this.piano.play(p); },
        onRelease: (p) => this.kb.setDown(p, false),
      });
      this.kb.showAllNames(true);
      this.hands = new HandsView(this.$canvas, keyLayout(low, high));
    }
    this.beat = 0;
    this.nextFinger = 0;
    this.state = null;
    this.$msg.textContent = "";
    this.$msg.className = "dr-msg";
    this.$progress.innerHTML = "";
    this.$big.classList.add("hidden");
    this._targets([]);
    this._resize();
  }

  async start(body, { onPass = null, onState = null } = {}) {
    this.onPass = onPass;
    this.onState = onState;
    this._clearHint();
    if (!this.piano.started) this.piano.start().catch(() => {});
    const s = await this.api("/api/drill/start", body);
    this.run = s.run;
    this._onState(s);
    return s;
  }

  stop() {
    if (this.run === null) return;
    this.run = null;
    this._clearHint();
    this.api("/api/drill/stop", {}).catch(() => {});
  }

  get active() {
    return !!(this.state && this.state.status === "active" && this.run !== null);
  }

  // ------------------------------------------------------------------ state

  _onState(s) {
    if (this.state && s.seq < this.state.seq) return;
    this.state = s;
    if (s.kind === "collect") this._collect(s);
    else if (s.kind === "find_key") this._find(s);
    else this._steps(s);
    if (s.status === "passed") {
      this._say("Well done! You did it.", "ok");
      this._targets([]);
      const cb = this.onPass;
      this.onPass = null;
      this.run = null;
      if (cb) cb(s);
    } else if (s.last === "try_ok") {
      this._say(`Good. ${s.tries_ok} of ${s.tries} done.`, "ok");
    } else if (s.last === "hold") {
      this._say("Keep the key down.", "go");
    }
    if (this.onState) this.onState(s);
    this._draw();
  }

  _onWrong(e) {
    const t = FAIL_TEXT[e.reason] || FAIL_TEXT.wrong_key;
    const many = this.state && this.state.tries > 1;
    this._say(t[many ? "many" : "one"], "bad");
    this._flash(e.pitch, "wrong");
  }

  _collect(s) {
    const got = new Set(s.collected);
    this.$progress.innerHTML = `<span class="dr-count">${got.size} of ${s.pitches.length}</span>`;
    this.kb.setMarked("hit", [...got]);
    const hint = !this.opts.hintAfterWrong || s.wrong >= 2;
    this._targets(s.status === "active" && hint ? s.pitches.filter((p) => !got.has(p)) : [], "R");
    if (s.status === "active" && s.last !== "wrong_key") this._say(got.size ? "Good. Find the next one." : "Press the keys on your keyboard.", "");
  }

  _steps(s) {
    const steps = s.steps || [];
    const chips = steps.map((st, i) => {
      const cls = s.status === "passed" || i < s.step ? "done" : i === s.step ? "now" : "";
      return `<span class="dr-chip ${cls}">${this._stepLabel(st)}</span>`;
    }).join("");
    const tries = s.tries > 1
      ? `<span class="dr-tries" aria-label="${s.tries_ok} of ${s.tries} done">${Array.from({ length: s.tries }, (_, i) => `<i class="${i < s.tries_ok ? "on" : ""}"></i>`).join("")}</span>`
      : "";
    this.$progress.innerHTML = `${tries}<span class="dr-chips">${chips}</span>`;
    const exp = s.status === "active" ? s.expect : null;
    const hand = exp && exp.hand === "L" ? "L" : "R";
    const keys = exp ? exp.all || exp.any || [] : [];
    const showKeys = this.opts.show !== "finger" && keys.length <= 6 && (!this.opts.hintAfterWrong || s.wrong >= 2);
    this._targets(showKeys ? keys : [], hand, exp && exp.all ? null : null);
    // The big text: finger number, soft/loud.
    let big = "";
    if (exp && exp.vel) big = exp.vel === "soft" ? "Soft" : "Loud";
    else if (exp && this.opts.show === "finger" && exp.finger) big = `Finger ${exp.finger}`;
    this.$big.textContent = big;
    this.$big.classList.toggle("hidden", !big);
    this.beat = this.opts.stepBeats ? (this.opts.stepBeats[s.step] ?? 0) : 0;
    this.nextFinger = exp ? exp.finger || 0 : 0;
    if (s.status === "active" && !["wrong_key", "too_short", "too_early", "too_soft", "too_loud", "try_ok", "hold"].includes(s.last)) {
      this._say(exp && exp.rest ? "Lift your hand. Wait 1 count. Then press." : exp && exp.hold ? "Press the key and hold it down." : "", "go");
    }
  }

  _stepLabel(st) {
    if (st.vel) return st.vel === "soft" ? "soft" : "loud";
    const keys = st.all || st.any || [];
    const names = keys.length > 3 ? "key" : keys.map((p) => keyName(p)).join("+");
    const f = st.finger ? ` <small>${st.finger}</small>` : "";
    return `${st.rest ? "… " : ""}${names}${f}${st.hold ? " ―" : ""}`;
  }

  _find(s) {
    this.$progress.innerHTML = `<span class="dr-count">${Math.min(s.round + (s.status === "active" ? 1 : 0), s.rounds)} of ${s.rounds}</span>`;
    this._clearHint();
    if (s.status === "active" && s.target) {
      this.$big.textContent = `Play ${s.target.name}`;
      this.$big.classList.remove("hidden");
      this._targets([]);
      const near = s.target.pitches.reduce((a, b) => (Math.abs(b - 60) < Math.abs(a - 60) ? b : a));
      this._hint = setTimeout(() => this._targets([near], "R"), HINT_MS);
      if (s.last === "hit") this._say(`Good. ${s.times.at(-1).toFixed(1)} seconds.`, "ok");
      else if (s.last !== "wrong_key") this._say("Press any key with this name. Be fast.", "");
    } else if (s.status === "passed") {
      const avg = s.times.length ? s.times.reduce((a, b) => a + b, 0) / s.times.length : 0;
      this.$big.textContent = `${avg.toFixed(1)} seconds for each key`;
      this.$big.classList.remove("hidden");
    }
  }

  _clearHint() {
    clearTimeout(this._hint);
    this._hint = null;
  }

  // ------------------------------------------------------------------ demo (skill moments)

  // Play the demo notes with key glow, the hand outline and the Mac sound (and clicks).
  async demo(demo) {
    if (!this.piano.started) await this.piano.start().catch(() => {});
    this._demoStop = false;
    const notes = demo.notes;
    const end = Math.max(...notes.map((n) => n.start + (n.dur || 1)));
    const groups = [...new Set(notes.map((n) => n.start))].sort((a, b) => a - b);
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    this._say("Watch and listen.", "go");
    const t0 = performance.now();
    if (demo.clicks) {
      for (let b = 0; b < Math.ceil(end); b++) {
        setTimeout(() => { if (!this._demoStop) this.piano.clickAt(this.piano.audioNow() + 0.01, b % 4 === 0); }, b * DEMO_BEAT_MS);
      }
    }
    for (const g of groups) {
      const at = t0 + g * DEMO_BEAT_MS;
      await wait(Math.max(0, at - performance.now()));
      if (this._demoStop) break;
      const now = notes.filter((n) => n.start === g);
      this.beat = g;
      this.nextFinger = now[0].finger || 0;
      this._demoHand = now[0].hand;
      for (const n of now) {
        this.kb.mark(n.pitch, `play-${n.hand}`, true);
        this.piano.play(n.pitch, ((n.dur || 1) * DEMO_BEAT_MS * 0.9) / 1000);
        setTimeout(() => this.kb.mark(n.pitch, `play-${n.hand}`, false), (n.dur || 1) * DEMO_BEAT_MS * 0.9);
      }
      this._draw();
    }
    await wait(Math.max(0, t0 + end * DEMO_BEAT_MS - performance.now()));
    this.beat = 0;
    this.nextFinger = 0;
    this._draw();
    if (!this._demoStop) this._say("", "");
  }

  stopDemo() {
    this._demoStop = true;
  }

  // ------------------------------------------------------------------ drawing

  _targets(pitches, hand = "R") {
    this.kb.setMarked("target-R", hand === "R" ? pitches : []);
    this.kb.setMarked("target-L", hand === "L" ? pitches : []);
  }

  _flash(pitch, kind) {
    this.kb.mark(pitch, kind, true);
    const keep = kind === "hit" && this.state && this.state.kind === "collect";
    if (!keep) setTimeout(() => this.kb.mark(pitch, kind, false), 350);
  }

  _say(text, kind) {
    this.$msg.textContent = text;
    this.$msg.className = `dr-msg ${kind}`;
  }

  _resize() {
    if (!this.el.offsetParent) return;
    this.hands.resize();
    this._draw();
  }

  _draw() {
    if (!this.hands || !this.hands.w) return;
    const list = [];
    const pos = this.opts.positions || [];
    for (const h of ["R", "L"]) {
      const mine = pos.filter((p) => p.hand === h).sort((a, b) => a.start - b.start);
      if (!mine.length) continue;
      const { pos: p, next } = positionAt(mine, this.beat);
      list.push({ hand: h, pos: p, next, active: true, nextFinger: this._fingerFor(h) });
    }
    const colors = {
      R: cssVar("--hand-right"), L: cssVar("--hand-left"),
      on: { R: cssVar("--on-hand-right"), L: cssVar("--on-hand-left") }, dotEdge: cssVar("--dot-edge"),
    };
    this.hands.draw(list, this.beat, colors, this.reducedMotion.matches);
  }

  _fingerFor(hand) {
    const s = this.state;
    const exp = s && s.status === "active" ? s.expect : null;
    if (this._demoHand && !exp) return this._demoHand === hand ? this.nextFinger : 0;
    if (!exp) return 0;
    if (exp.fingers && exp.all) {
      const p = exp.all.find((x) => (hand === "L" ? x < 60 : x >= 60));
      return p !== undefined ? exp.fingers[String(p)] || 0 : 0;
    }
    return (exp.hand || "R") === hand ? exp.finger || 0 : 0;
  }
}
