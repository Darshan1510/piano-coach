// Song editor (PLAN 11.4, Phase 5a): a piano-roll view on a Canvas.
// Select, drag (time and key), remove, add, change the length; hand and finger for a note or a
// selection; parts and the loop; speed and key; play from the line (Mac sound). Undo/redo for
// the last edits. Save sends the whole song to /api/editor/save (the app checks it there).
// Built-in songs are read-only: "Save as my copy".
// Words (PLAN 7.4): "click", "group of clicks", "speed", "the line", "part", "keys together".

const $ = (id) => document.getElementById(id);
const LOW = 36;
const HIGH = 96;
const GUTTER = 46; // px: key names on the left
const RULER = 24; // px: parts, the loop and the line at the top
const EDGE = 6; // px: grab the right end of a note to change its length
const UNDO_MAX = 60;
const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const isBlack = (p) => [1, 3, 6, 8, 10].includes(p % 12);

let keySeq = 1; // a local key for each note (selection survives sorting)

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export class EditorScreen {
  constructor({ api, piano, startSound, onPractice, onBack, getCourse }) {
    this.api = api;
    this.piano = piano;
    this.startSound = startSound || (async () => {});
    this.onPractice = onPractice || (() => {});
    this.onBack = onBack || (() => {});
    this.getCourse = getCourse || (() => null);
    this.song = null;
    this.songId = null;
    this.userSong = false;
    this.sel = new Set(); // note keys
    this.undoStack = [];
    this.redoStack = [];
    this.dirty = false;
    this.grid = 0.5; // beats
    this.pxPerBeat = 40;
    this.scrollBeat = 0;
    this.line = 0; // the play line (beats)
    this.drag = null;
    this.playing = null;
    this.visible = false;
    this.keys = [];
    this.canvas = $("ed-canvas");
    this.ctx = this.canvas.getContext("2d");
    this._bind();
    new ResizeObserver(() => this._resize()).observe($("ed-stage"));
    new MutationObserver(() => this.draw()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  }

  // ------------------------------------------------------------------ open / show

  async open(songId) {
    const r = await this.api(`/api/editor/${encodeURIComponent(songId)}`);
    this.stop();
    this.songId = r.song.id;
    this.userSong = r.user_song;
    this.keys = r.keys || [];
    this.song = this._load(r.song);
    this.sel.clear();
    this.undoStack = [];
    this.redoStack = [];
    this.dirty = false;
    this.line = 0;
    this.scrollBeat = 0;
    this.leaveArmed = false;
    $("ed-title").value = this.song.title;
    this._keyOptions();
    this._message("", "");
    this._renderAll();
    return this.song;
  }

  show() {
    this.visible = true;
    this._resize();
    $("ed-stage").focus({ preventScroll: true });
  }

  hide() {
    this.visible = false;
    this.stop();
  }

  _load(song) {
    const s = JSON.parse(JSON.stringify(song));
    for (const n of s.notes) n._k = keySeq++;
    s.sections = s.sections || [];
    s.loop = s.loop || null;
    return s;
  }

  // ------------------------------------------------------------------ the song model (edits)

  get notes() { return this.song ? this.song.notes : []; }
  get selected() { return this.notes.filter((n) => this.sel.has(n._k)); }
  get end() { return this.notes.reduce((m, n) => Math.max(m, n.start + n.dur), 0); }
  get group() { return this.song ? this.song.time_signature[0] : 4; }

  _snapshot() {
    const s = this.song;
    return JSON.stringify({ notes: s.notes, sections: s.sections, loop: s.loop, bpm: s.bpm, key: s.key, title: s.title });
  }

  _restore(text) {
    const o = JSON.parse(text);
    Object.assign(this.song, o);
    const keys = new Set(this.notes.map((n) => n._k));
    for (const k of [...this.sel]) if (!keys.has(k)) this.sel.delete(k);
  }

  // Each edit: keep the state before it (undo), then change, then draw.
  edit(fn) {
    const before = this._snapshot();
    const changed = fn() !== false;
    if (!changed || this._snapshot() === before) return false;
    this.undoStack.push(before);
    if (this.undoStack.length > UNDO_MAX) this.undoStack.shift();
    this.redoStack = [];
    this.dirty = true;
    this._sort();
    this._renderAll();
    return true;
  }

  undo() {
    if (!this.undoStack.length) return false;
    this.redoStack.push(this._snapshot());
    this._restore(this.undoStack.pop());
    this.dirty = true;
    this._renderAll();
    return true;
  }

  redo() {
    if (!this.redoStack.length) return false;
    this.undoStack.push(this._snapshot());
    this._restore(this.redoStack.pop());
    this.dirty = true;
    this._renderAll();
    return true;
  }

  _sort() { this.notes.sort((a, b) => a.start - b.start || a.pitch - b.pitch); }

  snap(beat) { return Math.round(beat / this.grid) * this.grid; }

  select(keys, add = false) {
    if (!add) this.sel.clear();
    for (const k of keys) this.sel.add(k);
    this._renderAll();
  }

  selectAll() { this.select(this.notes.map((n) => n._k)); }

  moveSelected(dBeats, dPitch) {
    return this.edit(() => {
      const sel = this.selected;
      if (!sel.length) return false;
      const minStart = Math.min(...sel.map((n) => n.start));
      const lo = Math.min(...sel.map((n) => n.pitch));
      const hi = Math.max(...sel.map((n) => n.pitch));
      const db = Math.max(dBeats, -minStart);
      const dp = Math.max(LOW - lo, Math.min(HIGH - hi, dPitch));
      for (const n of sel) {
        n.start = +(n.start + db).toFixed(4);
        n.pitch += dp;
        if (dp) n.finger = null; // a new key: the app gives a finger again at "Save" (or set it)
      }
    });
  }

  resizeSelected(dBeats) {
    return this.edit(() => {
      const sel = this.selected;
      if (!sel.length) return false;
      for (const n of sel) n.dur = Math.max(this.grid / 2, +(n.dur + dBeats).toFixed(4));
    });
  }

  setLength(dur) {
    return this.edit(() => { for (const n of this.selected) n.dur = Math.max(0.05, dur); });
  }

  deleteSelected() {
    return this.edit(() => {
      if (!this.sel.size) return false;
      this.song.notes = this.notes.filter((n) => !this.sel.has(n._k));
      this.sel.clear();
    });
  }

  addNote(pitch, start, dur = this.grid * 2, hand = null) {
    let added = null;
    this.edit(() => {
      if (pitch < LOW || pitch > HIGH || start < 0) return false;
      if (this.notes.some((n) => n.pitch === pitch && Math.abs(n.start - start) < 1e-6)) return false;
      added = { id: -1, pitch, start: +start.toFixed(4), dur, hand: hand || (pitch >= 60 ? "R" : "L"), finger: null, vel: 80, _k: keySeq++ };
      this.notes.push(added);
      this.sel.clear();
      this.sel.add(added._k);
    });
    return added;
  }

  setHand(hand) {
    return this.edit(() => {
      for (const n of this.selected) { if (n.hand !== hand) { n.hand = hand; n.finger = null; } }
    });
  }

  setFinger(finger) {
    return this.edit(() => { for (const n of this.selected) n.finger = finger; });
  }

  setBpm(bpm) {
    const v = Number(bpm);
    if (!Number.isFinite(v)) return false;
    return this.edit(() => { this.song.bpm = Math.round(v * 100) / 100; });
  }

  setKey(key) { return this.edit(() => { this.song.key = key; }); }

  setTitle(title) { return this.edit(() => { this.song.title = title; }); }

  // Parts: a list of [start, end) places that cover the song. "New part at the line" splits the
  // part under the line; "Join" removes the start of a part (it joins the part before).
  _parts() {
    const s = this.song.sections;
    if (s.length) return s;
    const end = Math.max(this.group, Math.ceil(this.end / this.group) * this.group);
    return [{ name: "Part 1", start: 0, end }];
  }

  splitPartAt(beat) {
    const b = this.snap(beat);
    return this.edit(() => {
      const parts = this._parts().map((p) => ({ ...p }));
      const i = parts.findIndex((p) => b > p.start + 1e-6 && b < p.end - 1e-6);
      if (i < 0) return false;
      parts.splice(i + 1, 0, { name: "", start: b, end: parts[i].end });
      parts[i].end = b;
      this.song.sections = this._named(parts);
    });
  }

  joinPart(i) {
    return this.edit(() => {
      const parts = this._parts().map((p) => ({ ...p }));
      if (i <= 0 || i >= parts.length) return false;
      parts[i - 1].end = parts[i].end;
      parts.splice(i, 1);
      this.song.sections = this._named(parts);
    });
  }

  // A part keeps its own name (for example "Verse"); "Part N" names are counted again.
  _named(parts) {
    return parts.map((p, i) => ({ name: p.name && !/^Part \d+$/.test(p.name) ? p.name : `Part ${i + 1}`, start: p.start, end: p.end }));
  }

  setLoop(start, end) {
    return this.edit(() => {
      const a = Math.max(0, Math.min(start, end));
      const b = Math.max(start, end);
      if (b - a < 0.5) return false;
      this.song.loop = { start: this.snap(a), end: this.snap(b) };
    });
  }

  setLoopStart(beat) {
    const cur = this.song.loop;
    const end = cur ? cur.end : Math.min(this.end, beat + this.group * 2);
    return this.setLoop(beat, Math.max(end, beat + 0.5));
  }

  setLoopEnd(beat) {
    const cur = this.song.loop;
    return this.setLoop(cur ? cur.start : Math.max(0, beat - this.group * 2), beat);
  }

  clearLoop() { return this.edit(() => { if (!this.song.loop) return false; this.song.loop = null; }); }

  setLine(beat) {
    this.line = Math.max(0, this.snap(beat));
    this._renderSide();
    this.draw();
  }

  // The song that goes to the app (no local keys).
  payload() {
    const s = this.song;
    return {
      title: $("ed-title").value.trim() || s.title, bpm: s.bpm, key: s.key || "", time_signature: s.time_signature,
      notes: s.notes.map((n) => ({ pitch: n.pitch, start: n.start, dur: n.dur, hand: n.hand, finger: n.finger ?? null, vel: n.vel ?? 80 })),
      sections: s.sections.map((p) => ({ name: p.name, start: p.start, end: p.end })), loop: s.loop,
    };
  }

  // Quick checks on the page; the app checks everything again.
  localCheck() {
    if (!this.notes.length) return "The song has no notes. Add one or more notes.";
    if (!($("ed-title").value.trim())) return "Give the song a name.";
    const bpm = Number(this.song.bpm);
    if (!(bpm >= 20 && bpm <= 300)) return "Set a speed from 20 to 300.";
    return "";
  }

  async save(asCopy = false) {
    const bad = this.localCheck();
    if (bad) { this._message(bad, "bad"); return null; }
    this._message("The app saves the song …", "");
    try {
      const r = await this.api("/api/editor/save", { song_id: this.songId, song: this.payload(), copy: !!asCopy });
      const keepSel = this.selected.map((n) => [n.pitch, n.start]);
      this.songId = r.song.id;
      this.userSong = true;
      this.song = this._load(r.song);
      this.sel = new Set(this.notes.filter((n) => keepSel.some(([p, s]) => p === n.pitch && Math.abs(s - n.start) < 1e-6)).map((n) => n._k));
      this.dirty = false;
      $("ed-title").value = this.song.title;
      const what = asCopy ? "The app saved your copy." : "The app saved the song.";
      this._message(`${what} ${r.card.difficulty ? r.card.difficulty.text : ""}`.trim(), "good");
      this._renderAll();
      return r;
    } catch (e) {
      this._message(e.message, "bad");
      return null;
    }
  }

  // ------------------------------------------------------------------ play from the line (Mac sound)

  async play() {
    if (this.playing) { this.stop(); return; }
    await this.startSound();
    const spb = 60 / this.song.bpm;
    const t0 = this.piano.audioNow() + 0.15;
    const from = this.line;
    const notes = this.notes.filter((n) => n.start >= from - 1e-6).sort((a, b) => a.start - b.start);
    const end = Math.max(from, this.end);
    this.playing = { t0, from, spb, notes, i: 0, end, id: (this._playId = (this._playId || 0) + 1) };
    $("ed-play").textContent = "Stop";
    const step = () => {
      const p = this.playing;
      if (!p || p.id !== this._playId) return;
      const now = this.piano.audioNow();
      const beat = p.from + (now - p.t0) / p.spb;
      const ahead = beat + 0.4 / p.spb;
      while (p.i < p.notes.length && p.notes[p.i].start <= ahead) {
        const n = p.notes[p.i++];
        this.piano.playAt(n.pitch, p.t0 + (n.start - p.from) * p.spb, n.dur * p.spb, n.vel || 80);
      }
      this.playBeat = Math.max(p.from, beat);
      this._follow(this.playBeat);
      this.draw();
      if (beat > p.end + 0.5) { this.stop(); return; }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  stop() {
    if (!this.playing) return;
    this.playing = null;
    this.playBeat = null;
    this.piano.releaseAll();
    $("ed-play").textContent = "Play from the line";
    this.draw();
  }

  _follow(beat) {
    const w = this._viewBeats();
    if (beat > this.scrollBeat + w * 0.85 || beat < this.scrollBeat) {
      this.scrollBeat = Math.max(0, beat - w * 0.15);
      this._syncScroll();
    }
  }

  // ------------------------------------------------------------------ view

  _resize() {
    const box = $("ed-stage");
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(300, box.clientWidth);
    this.rowH = 9;
    const h = RULER + (HIGH - LOW + 1) * this.rowH;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.w = w;
    this.h = h;
    this._syncScroll();
    this.draw();
  }

  _viewBeats() { return (this.w - GUTTER) / this.pxPerBeat; }
  x(beat) { return GUTTER + (beat - this.scrollBeat) * this.pxPerBeat; }
  y(pitch) { return RULER + (HIGH - pitch) * this.rowH; }
  beatAt(x) { return this.scrollBeat + (x - GUTTER) / this.pxPerBeat; }
  pitchAt(y) { return HIGH - Math.floor((y - RULER) / this.rowH); }

  zoom(f) {
    const mid = this.scrollBeat + this._viewBeats() / 2;
    this.pxPerBeat = Math.max(10, Math.min(160, this.pxPerBeat * f));
    this.scrollBeat = Math.max(0, mid - this._viewBeats() / 2);
    this._syncScroll();
    this.draw();
  }

  _syncScroll() {
    const r = $("ed-scroll");
    const total = Math.max(this.end + this.group * 2, this._viewBeats());
    const max = Math.max(0, total - this._viewBeats());
    r.max = String(Math.ceil(max * 4));
    this.scrollBeat = Math.min(this.scrollBeat, max);
    r.value = String(Math.round(this.scrollBeat * 4));
  }

  draw() {
    if (!this.song || !this.w) return;
    const c = this.ctx;
    const col = {
      bg: cssVar("--stage-bg"), lane: cssVar("--stage-lane"), grid: cssVar("--stage-grid"), bar: cssVar("--stage-bar"),
      text: cssVar("--text"), muted: cssVar("--muted"), r: cssVar("--hand-right"), l: cssVar("--hand-left"),
      onR: cssVar("--on-hand-right"), onL: cssVar("--on-hand-left"), accent: cssVar("--accent"), soft: cssVar("--accent-soft"),
      band: cssVar("--stage-band"), edge: cssVar("--place-edge"), place: cssVar("--place-band"), mid: cssVar("--stage-middle-c"),
      surface: cssVar("--surface-2"), border: cssVar("--border"),
    };
    c.clearRect(0, 0, this.w, this.h);
    c.fillStyle = col.bg;
    c.fillRect(0, 0, this.w, this.h);
    // rows
    for (let p = LOW; p <= HIGH; p++) {
      const y = this.y(p);
      if (isBlack(p)) { c.fillStyle = col.lane; c.fillRect(GUTTER, y, this.w - GUTTER, this.rowH); }
      if (p === 60) { c.fillStyle = col.mid; c.fillRect(GUTTER, y, this.w - GUTTER, this.rowH); }
      if (p % 12 === 0) { c.fillStyle = col.grid; c.fillRect(GUTTER, y + this.rowH - 1, this.w - GUTTER, 1); }
    }
    // loop band
    const s = this.song;
    if (s.loop) {
      c.fillStyle = col.place;
      c.fillRect(this.x(s.loop.start), RULER, (s.loop.end - s.loop.start) * this.pxPerBeat, this.h - RULER);
    }
    // click lines and group lines
    const first = Math.floor(this.scrollBeat);
    const last = Math.ceil(this.scrollBeat + this._viewBeats());
    const barsShown = !!(this.getCourse() || {}).bar_lines;
    for (let b = first; b <= last; b++) {
      const x = Math.round(this.x(b)) + 0.5;
      if (x < GUTTER) continue;
      const strong = b % this.group === 0;
      c.fillStyle = strong ? col.bar : col.grid;
      c.fillRect(x, RULER, 1, this.h - RULER);
      if (strong && barsShown && this.pxPerBeat * this.group > 28) {
        c.fillStyle = col.muted;
        c.font = "10px -apple-system, sans-serif";
        c.fillText(String(b / this.group + 1), x + 3, RULER + 10);
      }
    }
    // notes
    c.font = "bold 9px -apple-system, sans-serif";
    c.textBaseline = "middle";
    for (const n of this.notes) {
      const x = this.x(n.start);
      const w = Math.max(3, n.dur * this.pxPerBeat - 1);
      if (x + w < GUTTER || x > this.w) continue;
      const y = this.y(n.pitch) + 1;
      const hgt = this.rowH - 2;
      const on = this.sel.has(n._k);
      c.fillStyle = n.hand === "R" ? col.r : col.l;
      c.globalAlpha = on ? 1 : 0.82;
      c.fillRect(x, y, w, hgt);
      c.globalAlpha = 1;
      if (on) { c.strokeStyle = col.text; c.lineWidth = 2; c.strokeRect(x - 1, y - 1, w + 2, hgt + 2); }
      if (n.finger && w > 10) {
        c.fillStyle = n.hand === "R" ? col.onR : col.onL;
        c.fillText(String(n.finger), x + 3, y + hgt / 2 + 0.5);
      }
    }
    // rubber band
    if (this.drag && this.drag.kind === "band") {
      const d = this.drag;
      c.strokeStyle = col.accent;
      c.fillStyle = col.soft;
      c.lineWidth = 1;
      const x = Math.min(d.x0, d.x1);
      const y = Math.min(d.y0, d.y1);
      c.fillRect(x, y, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0));
      c.strokeRect(x + 0.5, y + 0.5, Math.abs(d.x1 - d.x0), Math.abs(d.y1 - d.y0));
    }
    // gutter with key names
    c.fillStyle = col.surface;
    c.fillRect(0, 0, GUTTER, this.h);
    c.fillStyle = col.border;
    c.fillRect(GUTTER - 1, 0, 1, this.h);
    c.font = "10px -apple-system, sans-serif";
    for (let p = LOW; p <= HIGH; p++) {
      if (p % 12 !== 0) continue;
      c.fillStyle = p === 60 ? col.edge : col.muted;
      c.fillText(p === 60 ? "Mid C" : "C", 6, this.y(p) + this.rowH / 2);
    }
    // ruler: parts, the loop, the line
    c.fillStyle = col.surface;
    c.fillRect(GUTTER, 0, this.w - GUTTER, RULER);
    c.fillStyle = col.border;
    c.fillRect(GUTTER, RULER - 1, this.w - GUTTER, 1);
    c.font = "11px -apple-system, sans-serif";
    for (const [i, p] of this._parts().entries()) {
      const x = this.x(p.start);
      if (x > this.w || this.x(p.end) < GUTTER) continue;
      c.fillStyle = i % 2 ? col.band : col.soft;
      c.fillRect(Math.max(GUTTER, x), 2, Math.min(this.w, this.x(p.end)) - Math.max(GUTTER, x) - 1, 9);
      c.fillStyle = col.muted;
      if (x >= GUTTER - 2) c.fillText(p.name, x + 3, 17);
    }
    if (s.loop) {
      c.fillStyle = col.edge;
      const a = this.x(s.loop.start);
      const b = this.x(s.loop.end);
      c.fillRect(Math.max(GUTTER, a), RULER - 4, Math.max(0, b - Math.max(GUTTER, a)), 3);
    }
    const line = this.playBeat != null ? this.playBeat : this.line;
    const lx = Math.round(this.x(line)) + 0.5;
    if (lx >= GUTTER) {
      c.fillStyle = col.accent;
      c.fillRect(lx - 1, 0, 2, this.h);
      c.beginPath();
      c.moveTo(lx - 6, 0); c.lineTo(lx + 6, 0); c.lineTo(lx, 8); c.closePath();
      c.fill();
    }
    c.textBaseline = "alphabetic";
  }

  // ------------------------------------------------------------------ mouse and keys

  _hit(x, y) {
    if (y < RULER) return null;
    const p = this.pitchAt(y);
    const b = this.beatAt(x);
    let best = null;
    for (const n of this.notes) {
      if (n.pitch !== p) continue;
      if (b >= n.start - 1e-6 && b <= n.start + n.dur + 2 / this.pxPerBeat) {
        const edge = x >= this.x(n.start + n.dur) - EDGE;
        best = { note: n, edge };
      }
    }
    return best;
  }

  _pos(e) {
    const r = this.canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }

  _down(e) {
    if (e.button !== 0) return;
    $("ed-stage").focus({ preventScroll: true });
    const [x, y] = this._pos(e);
    if (x < GUTTER) return;
    if (y < RULER) { this.setLine(this.beatAt(x)); this.drag = { kind: "line" }; return; }
    const hit = this._hit(x, y);
    if (hit) {
      if (e.shiftKey || e.metaKey) {
        if (this.sel.has(hit.note._k)) this.sel.delete(hit.note._k); else this.sel.add(hit.note._k);
        this._renderAll();
        return;
      }
      if (!this.sel.has(hit.note._k)) this.select([hit.note._k]);
      this.drag = { kind: hit.edge ? "size" : "move", x0: x, y0: y, b0: this.beatAt(x), p0: this.pitchAt(y), before: this._snapshot(),
        orig: this.selected.map((n) => ({ n, start: n.start, pitch: n.pitch, dur: n.dur, finger: n.finger })), moved: false };
      return;
    }
    this.drag = { kind: "band", x0: x, y0: y, x1: x, y1: y, add: e.shiftKey };
  }

  _move(e) {
    const [x, y] = this._pos(e);
    const d = this.drag;
    if (!d) {
      const hit = x > GUTTER && y > RULER ? this._hit(x, y) : null;
      this.canvas.style.cursor = hit ? (hit.edge ? "ew-resize" : "grab") : y < RULER ? "pointer" : "crosshair";
      return;
    }
    if (d.kind === "line") { this.setLine(this.beatAt(x)); return; }
    if (d.kind === "band") { d.x1 = x; d.y1 = y; this.draw(); return; }
    const db = this.snap(this.beatAt(x) - d.b0);
    if (d.kind === "move") {
      const dp = this.pitchAt(y) - d.p0;
      const minStart = Math.min(...d.orig.map((o) => o.start));
      const lo = Math.min(...d.orig.map((o) => o.pitch));
      const hi = Math.max(...d.orig.map((o) => o.pitch));
      const b = Math.max(db, -minStart);
      const p = Math.max(LOW - lo, Math.min(HIGH - hi, dp));
      for (const o of d.orig) {
        o.n.start = +(o.start + b).toFixed(4);
        o.n.pitch = o.pitch + p;
        o.n.finger = p ? null : o.finger;
      }
      d.moved = d.moved || b !== 0 || p !== 0;
    } else {
      for (const o of d.orig) o.n.dur = Math.max(this.grid / 2, +(o.dur + db).toFixed(4));
      d.moved = d.moved || db !== 0;
    }
    this.draw();
  }

  _up() {
    const d = this.drag;
    this.drag = null;
    if (!d) return;
    if (d.kind === "band") {
      const b0 = this.beatAt(Math.min(d.x0, d.x1));
      const b1 = this.beatAt(Math.max(d.x0, d.x1));
      const p0 = this.pitchAt(Math.max(d.y0, d.y1));
      const p1 = this.pitchAt(Math.min(d.y0, d.y1));
      if (Math.abs(d.x1 - d.x0) < 3 && Math.abs(d.y1 - d.y0) < 3) {
        if (!d.add) this.select([]);
        return;
      }
      const keys = this.notes.filter((n) => n.pitch >= p0 && n.pitch <= p1 && n.start + n.dur > b0 && n.start < b1).map((n) => n._k);
      this.select(keys, d.add);
      return;
    }
    if (d.kind === "line") return;
    if (d.moved && this._snapshot() !== d.before) {
      this.undoStack.push(d.before);
      if (this.undoStack.length > UNDO_MAX) this.undoStack.shift();
      this.redoStack = [];
      this.dirty = true;
      this._sort();
    }
    this._renderAll();
  }

  _dbl(e) {
    const [x, y] = this._pos(e);
    if (x < GUTTER || y < RULER || this._hit(x, y)) return;
    const b = Math.max(0, Math.floor(this.beatAt(x) / this.grid) * this.grid);
    this.addNote(this.pitchAt(y), b, Math.max(this.grid, 1));
  }

  // Keyboard (only when the note area has the focus, so that Space and Enter still work on the
  // buttons): Space = play / stop, Tab or ] = the next note, Shift+Tab or [ = the note before,
  // A = add a note at the line, arrows = move the selected notes (Shift = octave, Alt = length)
  // or, with no selection, move the line; Delete = remove; Escape = select no note.
  _key(e) {
    if (!this.visible || !this.song) return;
    if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); return; }
    const stage = $("ed-stage");
    if (!(stage && (document.activeElement === stage || stage.contains(document.activeElement)))) return;
    if (mod && e.key.toLowerCase() === "a") { e.preventDefault(); this.selectAll(); return; }
    if (mod || e.metaKey) return;
    if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); this.deleteSelected(); return; }
    if (e.key === " ") { e.preventDefault(); this.play(); return; }
    if (e.key === "Escape") { this.select([]); return; }
    if (e.key === "Tab" || e.key === "[" || e.key === "]") {
      const back = e.key === "[" || (e.key === "Tab" && e.shiftKey);
      // Tab leaves the note area after the last note (no keyboard trap).
      if (this.selectStep(back ? -1 : 1) || e.key !== "Tab") e.preventDefault();
      return;
    }
    if (e.key.toLowerCase() === "a" && !e.altKey) {
      e.preventDefault();
      const ref = this.selected[0] || this.notes.filter((n) => n.start <= this.line + 1e-6).pop();
      this.addNote(ref ? ref.pitch : 60, this.line, Math.max(this.grid, 1), ref ? ref.hand : null);
      this._follow(this.line);
      return;
    }
    const arrows = { ArrowUp: [0, 1], ArrowDown: [0, -1], ArrowLeft: [-this.grid, 0], ArrowRight: [this.grid, 0] };
    if (!arrows[e.key]) return;
    e.preventDefault();
    const [db, dp] = arrows[e.key];
    if (this.sel.size) {
      if (e.altKey && db) this.resizeSelected(db); else this.moveSelected(db, e.shiftKey ? dp * 12 : dp);
      const first = this.selected[0];
      if (first) this._follow(first.start);
    } else if (db) {
      this.setLine(this.line + db * (e.shiftKey ? 4 : 1));
      this._follow(this.line);
      this.draw();
    }
  }

  // Select the next (step 1) or the previous (step -1) note, in time order. Returns false when
  // there is no such note.
  selectStep(step) {
    if (!this.notes.length) return false;
    this._sort();
    const cur = this.selected;
    let i;
    if (!cur.length) {
      i = step > 0 ? this.notes.findIndex((n) => n.start >= this.line - 1e-6) : -1;
      if (step < 0) for (let j = this.notes.length - 1; j >= 0; j--) if (this.notes[j].start < this.line - 1e-6) { i = j; break; }
      if (i < 0) i = step > 0 ? 0 : this.notes.length - 1;
    } else {
      const idx = this.notes.indexOf(step > 0 ? cur[cur.length - 1] : cur[0]);
      i = idx + step;
      if (i < 0 || i >= this.notes.length) return false;
    }
    const n = this.notes[i];
    this.select([n._k]);
    this.line = Math.max(0, n.start);
    this._follow(n.start);
    this._renderAll();
    return true;
  }

  _bind() {
    const cv = this.canvas;
    cv.addEventListener("mousedown", (e) => this._down(e));
    window.addEventListener("mousemove", (e) => { if (this.visible) this._move(e); });
    window.addEventListener("mouseup", () => { if (this.visible) this._up(); });
    cv.addEventListener("dblclick", (e) => this._dbl(e));
    cv.addEventListener("wheel", (e) => {
      const dx = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.shiftKey ? e.deltaY : 0;
      if (!dx) return;
      e.preventDefault();
      this.scrollBeat = Math.max(0, this.scrollBeat + dx / this.pxPerBeat);
      this._syncScroll();
      this.draw();
    }, { passive: false });
    document.addEventListener("keydown", (e) => this._key(e));
    $("ed-scroll").addEventListener("input", (e) => { this.scrollBeat = Number(e.target.value) / 4; this.draw(); });
    $("ed-zoom-in").addEventListener("click", () => this.zoom(1.4));
    $("ed-zoom-out").addEventListener("click", () => this.zoom(1 / 1.4));
    $("ed-undo").addEventListener("click", () => this.undo());
    $("ed-redo").addEventListener("click", () => this.redo());
    $("ed-play").addEventListener("click", () => this.play());
    $("ed-save").addEventListener("click", () => this.save(false));
    $("ed-copy").addEventListener("click", () => this.save(true));
    $("ed-practice").addEventListener("click", () => { if (!this.dirty) this.onPractice(this.songId); });
    $("ed-back").addEventListener("click", () => {
      if (this.dirty && !this.leaveArmed) {
        this.leaveArmed = true;
        this._message("The song has changes that are not saved. Click \"Back\" again to leave without saving.", "bad");
        return;
      }
      this.leaveArmed = false;
      this.onBack();
    });
    for (const b of document.querySelectorAll("#ed-grid .seg")) {
      b.addEventListener("click", () => {
        this.grid = Number(b.dataset.grid);
        for (const x of document.querySelectorAll("#ed-grid .seg")) x.setAttribute("aria-checked", String(x === b));
      });
    }
    $("ed-hand-r").addEventListener("click", () => this.setHand("R"));
    $("ed-hand-l").addEventListener("click", () => this.setHand("L"));
    for (const b of document.querySelectorAll("#ed-fingers [data-finger]")) {
      b.addEventListener("click", () => this.setFinger(b.dataset.finger === "auto" ? null : Number(b.dataset.finger)));
    }
    $("ed-delete").addEventListener("click", () => this.deleteSelected());
    $("ed-shorter").addEventListener("click", () => this.resizeSelected(-this.grid));
    $("ed-longer").addEventListener("click", () => this.resizeSelected(this.grid));
    $("ed-split").addEventListener("click", () => this.splitPartAt(this.line));
    $("ed-loop-start").addEventListener("click", () => this.setLoopStart(this.line));
    $("ed-loop-end").addEventListener("click", () => this.setLoopEnd(this.line));
    $("ed-loop-clear").addEventListener("click", () => this.clearLoop());
    $("ed-line-start").addEventListener("click", () => { this.setLine(0); this.scrollBeat = 0; this._syncScroll(); this.draw(); });
    $("ed-bpm").addEventListener("change", (e) => { if (!this.setBpm(e.target.value)) e.target.value = String(this.song.bpm); });
    $("ed-key").addEventListener("change", (e) => this.setKey(e.target.value));
    $("ed-title").addEventListener("change", (e) => this.setTitle(e.target.value.trim() || this.song.title));
  }

  // ------------------------------------------------------------------ side panel and buttons

  _keyOptions() {
    const sel = $("ed-key");
    sel.innerHTML = "";
    sel.appendChild(new Option("The app finds it", ""));
    const happy = this.keys.filter((k) => k.endsWith(" major"));
    const sad = this.keys.filter((k) => k.endsWith(" minor"));
    const add = (list, word) => {
      for (const k of list) sel.appendChild(new Option(`${k.split(" ")[0]}, ${word}`, k));
    };
    add(happy, "happy sound");
    add(sad, "sad sound");
    sel.value = this.keys.includes(this.song.key) ? this.song.key : "";
  }

  _message(text, kind) {
    const m = $("ed-message");
    m.textContent = text;
    m.className = `ed-message${kind ? ` ${kind}` : ""}${text ? "" : " hidden"}`;
  }

  _renderAll() {
    this._renderSide();
    this._syncScroll();
    this.draw();
  }

  _renderSide() {
    if (!this.song) return;
    const sel = this.selected;
    const n = sel.length;
    $("ed-sel-text").textContent = n === 0 ? "No notes are selected. Click a note, or drag a box around notes."
      : n === 1 ? `1 note is selected: ${NAMES[sel[0].pitch % 12]}, ${sel[0].hand === "R" ? "right hand" : "left hand"}, finger ${sel[0].finger || "—"}.`
        : `${n} notes are selected.`;
    for (const id of ["ed-hand-r", "ed-hand-l", "ed-delete", "ed-shorter", "ed-longer"]) $(id).disabled = n === 0;
    for (const b of document.querySelectorAll("#ed-fingers [data-finger]")) {
      b.disabled = n === 0;
      const f = b.dataset.finger === "auto" ? null : Number(b.dataset.finger);
      b.setAttribute("aria-pressed", String(n > 0 && sel.every((x) => (x.finger ?? null) === f)));
    }
    $("ed-hand-r").setAttribute("aria-pressed", String(n > 0 && sel.every((x) => x.hand === "R")));
    $("ed-hand-l").setAttribute("aria-pressed", String(n > 0 && sel.every((x) => x.hand === "L")));
    $("ed-undo").disabled = !this.undoStack.length;
    $("ed-redo").disabled = !this.redoStack.length;
    $("ed-save").classList.toggle("hidden", !this.userSong);
    $("ed-copy").textContent = this.userSong ? "Save as a copy" : "Save as my copy";
    $("ed-copy").classList.toggle("primary", !this.userSong);
    $("ed-save").classList.toggle("primary", this.userSong);
    $("ed-readonly").classList.toggle("hidden", this.userSong);
    $("ed-dirty").classList.toggle("hidden", !this.dirty);
    $("ed-practice").disabled = this.dirty;
    $("ed-bpm").value = String(this.song.bpm);
    $("ed-count").textContent = `${this.notes.length} notes`;
    const lineClick = Math.round(this.line * 100) / 100;
    $("ed-line-text").textContent = `The line is at click ${lineClick + 1}.`;
    // parts list
    const list = $("ed-parts");
    list.innerHTML = "";
    for (const [i, p] of this._parts().entries()) {
      const row = document.createElement("li");
      row.innerHTML = '<span class="ed-part-name"></span><span class="ed-part-place muted"></span>';
      row.querySelector(".ed-part-name").textContent = p.name;
      row.querySelector(".ed-part-place").textContent = `clicks ${+(p.start + 1).toFixed(2)} to ${+p.end.toFixed(2)}`;
      if (i > 0) {
        const b = document.createElement("button");
        b.className = "btn btn-sm btn-ghost";
        b.textContent = "Join with the part before";
        b.addEventListener("click", () => this.joinPart(i));
        row.appendChild(b);
      }
      list.appendChild(row);
    }
    const loop = this.song.loop;
    $("ed-loop-text").textContent = loop ? `The loop goes from click ${+(loop.start + 1).toFixed(2)} to click ${+loop.end.toFixed(2)}.`
      : "No loop. Move the line, then set the start and the end of the loop.";
    $("ed-loop-clear").disabled = !loop;
  }
}
