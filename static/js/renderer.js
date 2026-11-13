// Falling notes (Canvas 2D). Each note falls in the lane of its key and touches the line at the
// top of the keyboard at its start time. Song times are in beats; the caller gives the beat.
//
// Speed: the view shows LOOKAHEAD beats, so at a slow speed the notes fall slowly.
// Per frame: binary search for the first visible note, then draw only the visible notes.
// The lanes are drawn once into an off-screen canvas (after a resize or a theme change).
//
// PLAN 7.4 Rule 5: no bar lines before Level 3. practice.js sets showBarLines from the course level.

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
      countInFrom: null, label: "" };
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
      const y0 = Math.max(top, -4);
      const y1 = Math.min(bottom, h);
      const hh = Math.max(3, y1 - y0 - 2);
      const faded = !active || played;
      ctx.globalAlpha = !active ? 0.38 : played ? 0.45 : 1;
      ctx.fillStyle = colors[n.hand];
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
