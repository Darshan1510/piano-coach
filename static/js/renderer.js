// Falling notes (Canvas 2D). Each note falls in the lane of its key and touches the line at the
// top of the keyboard at its start time. Song times are in beats; the caller gives the beat.
//
// Speed: the view shows LOOKAHEAD beats, so at a slow speed the notes fall slowly.
// Per frame: binary search for the first visible note, then draw only the visible notes.
// The lanes are drawn once into an off-screen canvas (after a resize or a theme change).
//
// PLAN 7.4 Rule 5: no bar lines before Level 3. practice.js sets showBarLines from the course level.
// Phase 4: view.place = a place that a finding names (PLAN 7.4 Rule 1: a colored band across the
// notes); view.stopBeat = "Continue from here" (a dashed line). PreviewView = the small picture of
// one place for the after-run card, with the wrong notes in red.

import { roundRect } from "/static/js/hands.js";

const LOOKAHEAD = 4; // beats from the line to the top of the view
const WRONG_MS = 450;

export class FallingNotes {
  constructor(canvas, layout, { showBarLines = false } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d", { alpha: false });
    this.layout = layout;
    this.showBarLines = showBarLines;
    this.notes = [];
    this.starts = [];
    this.maxDur = 1;
    this.w = 0;
    this.h = 0;
    this.colors = null;
    this.bg = null;
    this.flashes = []; // {pitch, until}
    this.view = { active: new Set(["R"]), stops: null, stopIndex: 0, waiting: false, range: null, loop: false,
      countInFrom: null, label: "", place: null, stopBeat: null, results: null, chords: null };
  }

  setSong(song) {
    this.song = song;
    this.notes = [...song.notes].sort((a, b) => a.start - b.start || a.pitch - b.pitch);
    this.starts = this.notes.map((n) => n.start);
    this.maxDur = Math.max(1, ...this.notes.map((n) => n.dur));
    this.beatsPerGroup = song.time_signature ? song.time_signature[0] : 4;
  }

  // view: {active: Set of hands, stopBeats: sorted beats of wait stops, stopIndex, waiting, range, loop, label}
  setView(view) {
    Object.assign(this.view, view);
  }

  setColors(colors) {
    this.colors = colors;
    this._buildBackground();
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.dpr = dpr;
    this.w = r.width;
    this.h = r.height;
    this.canvas.width = Math.max(1, Math.round(r.width * dpr));
    this.canvas.height = Math.max(1, Math.round(r.height * dpr));
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this._lanes = new Map();
    for (const [p, g] of this.layout) {
      const x = (g.left / 100) * this.w;
      const w = (g.width / 100) * this.w;
      const pad = g.black ? 1 : Math.max(1.5, w * 0.08);
      this._lanes.set(p, { x: x + pad, w: w - pad * 2, black: g.black });
    }
    this._buildBackground();
  }

  _buildBackground() {
    if (!this.colors || !this.w) return;
    const dpr = this.dpr || 1;
    const bg = document.createElement("canvas");
    bg.width = this.canvas.width;
    bg.height = this.canvas.height;
    const c = bg.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.fillStyle = this.colors.bg;
    c.fillRect(0, 0, this.w, this.h);
    // Black-key lanes are a little darker, so each note's lane is easy to follow.
    c.fillStyle = this.colors.lane;
    for (const [p, g] of this.layout) {
      if (!g.black) continue;
      c.fillRect((g.left / 100) * this.w, 0, (g.width / 100) * this.w, this.h);
    }
    // A thin line left of each C (groups of 12 keys), and a soft band over middle C.
    c.fillStyle = this.colors.grid;
    for (const [p, g] of this.layout) {
      if (p % 12 === 0) c.fillRect(Math.round((g.left / 100) * this.w), 0, 1, this.h);
    }
    const mc = this.layout.get(60);
    if (mc) {
      c.fillStyle = this.colors.middleC;
      c.fillRect((mc.left / 100) * this.w, 0, (mc.width / 100) * this.w, this.h);
    }
    this.bg = bg;
  }

  flashWrong(pitch) {
    this.flashes.push({ pitch, until: performance.now() + WRONG_MS });
  }

  _firstIndex(beat) {
    // first note with start >= beat (binary search)
    let lo = 0;
    let hi = this.starts.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (this.starts[mid] < beat) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  }

  draw(beat, reducedMotion = false) {
    const ctx = this.ctx;
    const { w, h, colors, view } = this;
    if (!colors || !w || !h) return;
    if (this.bg) ctx.drawImage(this.bg, 0, 0, w, h);
    else { ctx.fillStyle = colors.bg; ctx.fillRect(0, 0, w, h); }
    const ppb = h / LOOKAHEAD;
    const yOf = (b) => h - (b - beat) * ppb;

    // The repeated part (loop): a colored band across the notes (PLAN 7.4 Rule 1: show the place).
    if (view.loop && view.range) {
      const top = Math.max(0, yOf(view.range[1]));
      const bottom = Math.min(h, yOf(view.range[0]));
      if (bottom > 0 && top < h) {
        ctx.fillStyle = colors.band;
        ctx.fillRect(0, top, w, bottom - top);
        ctx.fillStyle = colors.bandEdge;
        if (top > 0) ctx.fillRect(0, top, w, 2);
        if (bottom < h) ctx.fillRect(0, bottom - 2, w, 2);
      }
    }

    // A place that a finding names (Rule 1): a warm band with an edge.
    if (view.place) {
      const top = Math.max(0, yOf(view.place.end));
      const bottom = Math.min(h, yOf(view.place.start));
      if (bottom > 0 && top < h) {
        ctx.fillStyle = colors.placeBand || colors.band;
        ctx.fillRect(0, top, w, bottom - top);
        ctx.fillStyle = colors.placeEdge || colors.bandEdge;
        if (top > 0) ctx.fillRect(0, top, w, 3);
        if (bottom < h) ctx.fillRect(0, bottom - 3, w, 3);
      }
    }

    // From Level 3 (Rule 5): a thin line where each bar starts, with a small bar number.
    if (this.showBarLines) {
      const g = this.beatsPerGroup;
      ctx.font = `700 11px -apple-system, BlinkMacSystemFont, sans-serif`;
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      for (let b = Math.max(0, Math.ceil(beat / g) * g); b < beat + LOOKAHEAD; b += g) {
        const y = Math.round(yOf(b));
        ctx.fillStyle = colors.barLine || colors.grid;
        ctx.fillRect(0, y, w, 1);
        ctx.fillStyle = colors.text;
        ctx.globalAlpha = 0.7;
        ctx.fillText(String(Math.floor(b / g) + 1), 6, y - 2);
        ctx.globalAlpha = 1;
      }
    }

    // Lead-sheet mode (Phase 6): the names of the key groups on the left, where each one starts.
    if (view.chords && view.chords.length) {
      ctx.font = `800 13px -apple-system, BlinkMacSystemFont, sans-serif`;
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      for (const c of view.chords) {
        if (c.start + c.dur < beat || c.start > beat + LOOKAHEAD) continue;
        const y = Math.round(yOf(Math.max(c.start, beat)));
        ctx.fillStyle = colors.L;
        ctx.globalAlpha = 0.5;
        ctx.fillRect(0, Math.round(yOf(c.start)), w, 2);
        ctx.globalAlpha = 1;
        const tw = ctx.measureText(c.name).width + 12;
        ctx.fillStyle = colors.bg;
        ctx.fillRect(28, y - 20, tw, 18);
        ctx.fillStyle = colors.L;
        ctx.fillText(c.name, 34, y - 4);
      }
    }

    // Notes
    const font = Math.round(Math.min(15, Math.max(11, w / 80)));
    ctx.font = `800 ${font}px -apple-system, BlinkMacSystemFont, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const end = beat + LOOKAHEAD;
    const stopBeats = view.stopBeats;
    const doneBefore = stopBeats && view.stopIndex > 0
      ? (view.stopIndex < stopBeats.length ? stopBeats[view.stopIndex] : Infinity) : -Infinity;
    const waitBeat = view.waiting && stopBeats ? stopBeats[view.stopIndex] : null;
    for (let i = this._firstIndex(beat - this.maxDur); i < this.notes.length; i++) {
      const n = this.notes[i];
      if (n.start > end) break;
      const bottom = yOf(n.start);
      const top = yOf(n.start + n.dur);
      if (top >= h) continue; // already gone below the line
      const lane = this._lanes.get(n.pitch);
      if (!lane) continue;
      const active = view.active.has(n.hand);
      const played = active && stopBeats && n.start < doneBefore - 1e-6;
      const res = view.results ? view.results.get(n.id) : undefined; // play-along: a missed note is red
      const y0 = Math.max(top, -4);
      const y1 = Math.min(bottom, h);
      const hh = Math.max(3, y1 - y0 - 2);
      const faded = !active || played;
      ctx.globalAlpha = !active ? 0.38 : played ? 0.45 : 1;
      ctx.fillStyle = res === "miss" ? colors.bad : colors[n.hand];
      ctx.beginPath();
      roundRect(ctx, lane.x, y0 + 1, lane.w, hh, Math.min(7, lane.w / 3));
      ctx.fill();
      if (waitBeat !== null && active && Math.abs(n.start - waitBeat) < 1e-6) {
        ctx.lineWidth = 3;
        ctx.strokeStyle = colors.waitRing;
        ctx.stroke();
      }
      // Finger number inside the note, near its lower end (the end that touches the line first).
      if (n.finger && hh > font + 4 && lane.w > font * 0.9) {
        const cy = y0 + 1 + hh - Math.min(hh / 2, font * 0.95);
        // Contrast >= 4.5:1 (WCAG AA): on a solid note the hand's own text color; on a faded note
        // (other hand, or done) the page text color at full strength.
        ctx.globalAlpha = 1;
        ctx.fillStyle = faded ? colors.text : colors.on[n.hand];
        ctx.fillText(String(n.finger), lane.x + lane.w / 2, cy);
      }
    }
    ctx.globalAlpha = 1;

    // Wrong key: a short red mark at the line, in the lane of the key.
    if (this.flashes.length) {
      const now = performance.now();
      this.flashes = this.flashes.filter((f) => f.until > now);
      for (const f of this.flashes) {
        const lane = this._lanes.get(f.pitch);
        if (!lane) continue;
        ctx.globalAlpha = reducedMotion ? 0.9 : Math.max(0, (f.until - now) / WRONG_MS);
        ctx.fillStyle = colors.bad;
        ctx.fillRect(lane.x - 2, h - 44, lane.w + 4, 44);
      }
      ctx.globalAlpha = 1;
    }

    // The line: press the key when the note touches it.
    ctx.fillStyle = colors.line;
    ctx.fillRect(0, h - 3, w, 3);

    // "Continue from here": a dashed line at the stop point, with a label.
    if (view.stopBeat !== null && view.stopBeat !== undefined) {
      const y = Math.round(yOf(view.stopBeat)) - 2;
      if (y > 0 && y <= h) {
        ctx.strokeStyle = colors.placeEdge || colors.bandEdge;
        ctx.lineWidth = 3;
        ctx.setLineDash([10, 6]);
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = `700 13px -apple-system, BlinkMacSystemFont, sans-serif`;
        ctx.textAlign = "left";
        ctx.textBaseline = "bottom";
        ctx.fillStyle = colors.text;
        ctx.fillText("Continue from here", 10, y - 6);
      }
    }

    // Count-in: big numbers before the song starts (4 3 2 1).
    if (view.countInTo !== null && view.countInTo !== undefined && beat < view.countInTo - 1e-6) {
      const left = Math.ceil(view.countInTo - beat - 1e-6);
      ctx.fillStyle = colors.text;
      ctx.globalAlpha = 0.85;
      ctx.font = `800 ${Math.round(h / 4)}px -apple-system, BlinkMacSystemFont, sans-serif`;
      ctx.fillText(String(left), w / 2, h * 0.42);
      ctx.globalAlpha = 1;
    }
  }
}

// A small, still picture of one place of the song (PLAN 7.2 preview): the notes of the place fall
// to a short keyboard strip; wrong or missed notes are red, extra keys are red marks. "Show me"
// moves a line through it while the app plays the place.
export class PreviewView {
  constructor(canvas, { song, place, hands, log, colors }) {
    this.canvas = canvas;
    this.song = song;
    this.place = place;
    this.colors = colors;
    this.hands = new Set(hands);
    const ids = new Map((log && log.notes ? log.notes : []).map((n) => [`${n.start}|${n.pitch}|${n.hand}`, n]));
    this.notes = song.notes.filter((n) => n.start >= place.start - 1e-6 && n.start < place.end - 1e-6)
      .map((n) => ({ ...n, res: ids.get(`${n.start}|${n.pitch}|${n.hand}`) }));
    this.extras = (log && log.extras ? log.extras : []).filter((e) => e.beat >= place.start - 0.5 && e.beat < place.end);
    const pitches = [...this.notes.map((n) => n.pitch), ...this.extras.map((e) => e.pitch)];
    this.low = Math.min(...pitches, 60) - 2;
    this.high = Math.max(...pitches, 60) + 2;
    this.playBeat = null;
  }

  draw() {
    const c = this.canvas;
    const r = c.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    c.width = Math.max(1, Math.round(r.width * dpr));
    c.height = Math.max(1, Math.round(r.height * dpr));
    const ctx = c.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = r.width;
    const h = r.height;
    const kb = 16; // a key strip at the bottom
    const col = this.colors;
    ctx.fillStyle = col.bg;
    ctx.fillRect(0, 0, w, h);
    const keys = this.high - this.low + 1;
    const kw = w / keys;
    const span = this.place.end - this.place.start;
    const yOf = (b) => (h - kb) - ((b - this.place.start) / span) * (h - kb - 6);
    // key strip: white and black keys
    for (let p = this.low; p <= this.high; p++) {
      const black = [1, 3, 6, 8, 10].includes(((p % 12) + 12) % 12);
      ctx.fillStyle = black ? col.lane : col.keyWhite || "#e8edf6";
      ctx.fillRect((p - this.low) * kw + 0.5, h - kb, kw - 1, kb);
    }
    ctx.fillStyle = col.line;
    ctx.fillRect(0, h - kb - 2, w, 2);
    for (const n of this.notes) {
      const y0 = yOf(n.start + n.dur);
      const y1 = yOf(n.start);
      const wrong = n.res && n.res.grade === "miss";
      ctx.globalAlpha = this.hands.has(n.hand) ? 1 : 0.35;
      ctx.fillStyle = wrong ? col.bad : col[n.hand];
      ctx.fillRect((n.pitch - this.low) * kw + 1.5, Math.max(0, y0) + 1, kw - 3, Math.max(3, y1 - Math.max(0, y0) - 2));
      if (n.res && n.res.slip !== null && n.res.slip !== undefined) {
        // the key that the user pressed instead: a red outline in its lane
        ctx.strokeStyle = col.bad;
        ctx.lineWidth = 2;
        ctx.strokeRect((n.res.slip - this.low) * kw + 2, y1 - 10, kw - 4, 8);
      }
    }
    ctx.globalAlpha = 1;
    for (const e of this.extras) {
      if (e.slip_of !== null && e.slip_of !== undefined) continue;
      ctx.fillStyle = col.bad;
      ctx.beginPath();
      ctx.arc((e.pitch - this.low + 0.5) * kw, yOf(e.beat), Math.min(5, kw / 2.5), 0, Math.PI * 2);
      ctx.fill();
    }
    if (this.playBeat !== null) {
      ctx.fillStyle = col.text;
      ctx.fillRect(0, Math.round(yOf(this.playBeat)), w, 2);
    }
  }
}
