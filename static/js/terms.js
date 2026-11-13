// Music terms (PLAN 7.4 Rules 2-4). Before the unlock lesson, the app uses the plain word. After
// it, the term has a dotted underline; click it to see its card again. The first time after the
// unlock, the card shows with a "Got it" button.
//
// The words come from data/course/terms.json (through /api/course/terms). No term is written in
// this file: a locked term never reaches the screen.

import { Keyboard, WORDS } from "/static/js/keyboard.js";

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function cap(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

// One modal for the app (cards, warnings, celebrations). show() returns the clicked button id.
export class Modal {
  constructor() {
    this.el = document.getElementById("modal");
    this.card = document.getElementById("modal-card");
    this._resolve = null;
    this._opener = null; // the element with the focus before the modal opened (focus goes back to it)
    this.el.addEventListener("click", (e) => { if (e.target === this.el) this.close(null); });
    document.addEventListener("keydown", (e) => {
      if (this.el.classList.contains("hidden")) return;
      if (e.key === "Escape") { this.close(null); return; }
      if (e.key === "Tab") this._trap(e);
    });
    // Focus that goes out of the modal by other means (a click on the page behind) comes back.
    document.addEventListener("focusin", (e) => {
      if (!this.el.classList.contains("hidden") && !this.card.contains(e.target)) this._focusFirst();
    });
  }

  _focusables() {
    const sel = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
    return [...this.card.querySelectorAll(sel)].filter((x) => x.offsetParent !== null || x === document.activeElement);
  }

  _focusFirst() {
    const row = this.card.querySelector(".modal-buttons");
    const f = (row && (row.querySelector(".primary") || row.querySelector("button"))) || this._focusables()[0] || this.card;
    f.focus({ preventScroll: true });
  }

  // Tab and Shift+Tab stay inside the modal.
  _trap(e) {
    const list = this._focusables();
    if (!list.length) { e.preventDefault(); this.card.focus({ preventScroll: true }); return; }
    const first = list[0];
    const last = list[list.length - 1];
    const cur = document.activeElement;
    if (e.shiftKey && (cur === first || !this.card.contains(cur))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (cur === last || !this.card.contains(cur))) { e.preventDefault(); first.focus(); }
  }

  // {eyebrow, title, html, buttons: [{id, label, primary}], wide, onOpen(card)}
  show({ eyebrow = "", title = "", html = "", buttons = [{ id: "ok", label: "OK", primary: true }], wide = false, onOpen = null, tone = "" }) {
    const opener = this._resolve ? this._opener : document.activeElement;
    if (this._resolve) this.close(null, false);
    this._opener = opener && opener !== document.body ? opener : null;
    this.card.tabIndex = -1;
    this.card.className = `modal-card${wide ? " modal-wide" : ""}${tone ? ` modal-${tone}` : ""}`;
    this.card.innerHTML = `${eyebrow ? `<div class="card-eyebrow">${esc(eyebrow)}</div>` : ""}<h2 id="modal-title"></h2>
      <div class="modal-body">${html}</div><div class="btn-row modal-buttons"></div>`;
    this.card.querySelector("#modal-title").textContent = title;
    const row = this.card.querySelector(".modal-buttons");
    for (const b of buttons) {
      const btn = document.createElement("button");
      btn.className = `btn btn-lg${b.primary ? " primary" : ""}`;
      btn.textContent = b.label;
      btn.dataset.id = b.id;
      btn.addEventListener("click", () => { if (b.keepOpen) b.onClick && b.onClick(btn); else this.close(b.id); });
      row.appendChild(btn);
    }
    this.el.classList.remove("hidden");
    if (onOpen) onOpen(this.card);
    this._focusFirst();
    return new Promise((resolve) => { this._resolve = resolve; });
  }

  close(id, restore = true) {
    this.el.classList.add("hidden");
    this.card.innerHTML = "";
    const r = this._resolve;
    this._resolve = null;
    const opener = this._opener;
    this._opener = null;
    if (restore && opener && opener.isConnected) opener.focus({ preventScroll: true });
    if (r) r(id);
  }

  get open() {
    return !this.el.classList.contains("hidden");
  }
}

export class Terms {
  constructor({ api, modal, piano }) {
    this.api = api;
    this.modal = modal;
    this.piano = piano;
    this.list = [];
    this.byId = new Map();
    this.lockedCount = 0;
    this.handlers = [];
    this._queue = Promise.resolve();
    // Click (or Enter) on an underlined term: show its card again.
    const open = (el) => this.showCard(el.dataset.term);
    document.addEventListener("click", (e) => {
      const t = e.target.closest && e.target.closest(".term");
      if (t) { e.preventDefault(); e.stopPropagation(); open(t); }
    }, true);
    document.addEventListener("keydown", (e) => {
      const t = e.target.closest && e.target.closest(".term");
      if (t && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(t); }
    });
  }

  onChange(fn) { this.handlers.push(fn); }

  async load() {
    try {
      const r = await this.api("/api/course/terms");
      this.list = r.terms;
      this.lockedCount = r.locked_count;
    } catch { /* keep the old list */ }
    this.byId = new Map(this.list.map((t) => [t.id, t]));
    WORDS.sharpFlat = this.unlocked("sharp_flat"); // Level 4: black-key names (keyboard.js)
    for (const fn of this.handlers) fn();
    return this.list;
  }

  unlocked(id) {
    const t = this.byId.get(id);
    return !!(t && t.unlocked);
  }

  get known() {
    return this.list.filter((t) => t.unlocked);
  }

  // The word to show: the term after its unlock, else the plain word.
  word(id, { plural = false, capital = false } = {}) {
    const t = this.byId.get(id);
    if (!t) return "";
    const w = t.unlocked ? (plural ? t.plural : t.term) : (plural ? t.plain_plural : t.plain);
    return capital ? cap(w) : w;
  }

  // HTML: an unlocked term has a dotted underline and opens its card.
  html(id, opts = {}) {
    const w = esc(this.word(id, opts));
    return this.unlocked(id) ? `<span class="term" role="button" tabindex="0" data-term="${id}">${w}</span>` : w;
  }

  // Course text with the unlocked terms underlined. Strict: only the term marks that the server
  // puts in the text ([[id|shown words]], riyaz/course.py render_text) are terms. The server
  // already put the plain words for a locked term; no word search in the text (the English word
  // "rest" in "the rest of the song" is not the music term).
  markup(text) {
    return esc(text).replace(/\[\[([a-z_]+)(?:\|([^|\]]*))?(?:\|[^\]]*)?\]\]/g, (m, id, shown) => {
      const t = this.byId.get(id);
      if (!t || !t.unlocked) return t ? esc(t.plain) : ""; // the server sends plain words; this is a guard
      return `<span class="term" role="button" tabindex="0" data-term="${id}">${shown !== undefined ? shown : esc(t.term)}</span>`;
    });
  }

  // Plain text of a course text (no marks), for textContent and aria labels.
  plainText(text) {
    const tmp = document.createElement("div");
    tmp.innerHTML = this.markup(text);
    return tmp.textContent;
  }

  // Rule 3: the card shows the first time after the unlock. Cards wait for each other.
  firstUse(ids) {
    for (const id of ids || []) {
      const t = this.byId.get(id);
      if (t && t.unlocked && !t.seen) this._queue = this._queue.then(() => this.showCard(id, true));
    }
    return this._queue;
  }

  async showCard(id, first = false) {
    const t = this.byId.get(id);
    if (!t || !t.unlocked) return;
    const lowNote = t.demo && t.demo.kind === "keys" ? Math.min(...t.demo.notes.map((n) => n[0]).filter((p) => p > 0)) : 60;
    const low = lowNote < 48 ? 36 : 48;
    let kb = null;
    const result = await this.modal.show({
      eyebrow: first ? "New word" : "Word",
      title: cap(t.term),
      html: `<p class="term-card-text">${this.markup(t.card)}</p>
        ${t.demo ? '<div class="term-demo-kb keyboard-wrap mini"></div>' : ""}`,
      buttons: [
        ...(t.demo ? [{ id: "demo", label: "Show me", keepOpen: true, onClick: () => this.playDemo(t.demo, kb) }] : []),
        { id: "ok", label: "Got it", primary: true },
      ],
      onOpen: (card) => {
        const el = card.querySelector(".term-demo-kb");
        if (el) {
          kb = new Keyboard(el, { low, high: low + 24, compact: true });
          kb.mark(60, "target", false);
        }
      },
    });
    this._stopDemo = true;
    if (!t.seen) {
      t.seen = true;
      this.api(`/api/course/terms/${id}/seen`, {}).catch(() => {});
    }
    return result;
  }

  // A short demo (PLAN 7.4 Rule 4): the app highlights the keys and plays them, or plays clicks.
  async playDemo(demo, kb) {
    const piano = this.piano;
    this._stopDemo = false;
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    if (piano && !piano.started) await piano.start().catch(() => {});
    if (demo.kind === "clicks") {
      for (let i = 0; i < demo.count && !this._stopDemo; i++) {
        if (piano) piano.clickAt(piano.audioNow() + 0.02, i % (demo.group || 4) === 0);
        await wait(demo.ms || 600);
      }
      return;
    }
    const notes = demo.notes || [];
    const hand = demo.hand === "L" ? "play-L" : "play-R";
    for (let i = 0; i < notes.length && !this._stopDemo; i++) {
      const [pitch] = notes[i];
      const fast = demo.faster_half && i >= notes.length / 2;
      const ms = fast ? (demo.ms || 500) / 2 : demo.ms || 500;
      if (pitch > 0) {
        if (kb) kb.mark(pitch, hand, true);
        if (piano) piano.play(pitch, ms / 1000);
      }
      await wait(ms);
      if (kb && pitch > 0 && !(demo.together_end)) kb.mark(pitch, hand, false);
    }
    if (demo.together_end && !this._stopDemo) {
      const ps = notes.map((n) => n[0]).filter((p) => p > 0);
      for (const p of ps) if (piano) piano.play(p, 1.2);
      await wait(1300);
      if (kb) for (const p of ps) kb.mark(p, hand, false);
    }
  }
}
