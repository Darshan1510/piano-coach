// On-screen keyboard: 61 keys (MIDI 36-96), like the YPT-320.

const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const BLACK = new Set([1, 3, 6, 8, 10]);
export const MIDDLE_C = 60;

// Letter name with "#" for black keys. Code and checks use it. For text on the screen, use
// keyName() or shortKeyName(): they follow the beginner word rules.
export function noteName(pitch) {
  return NAMES[pitch % 12];
}

export function isBlack(pitch) {
  return BLACK.has(pitch % 12);
}

// PLAN 7.4: the words "sharp" and "flat" (and names like C#) unlock at Level 4. Before that, the
// screen shows no letter on a black key and uses "the black key right of C" in text.
// One flag: the course (Phase 3+) sets it to true at Level 4, then calls Keyboard.refreshLabels().
export const WORDS = { sharpFlat: false };

export function keyName(pitch) {
  if (isBlack(pitch) && !WORDS.sharpFlat) return `the black key right of ${NAMES[(pitch + 11) % 12]}`;
  return NAMES[pitch % 12];
}

// For short lists ("You press: C E G").
export function shortKeyName(pitch) {
  return isBlack(pitch) && !WORDS.sharpFlat ? "black key" : NAMES[pitch % 12];
}

function labelText(pitch) {
  return isBlack(pitch) && !WORDS.sharpFlat ? "" : NAMES[pitch % 12];
}

// Key places in % of the keyboard width. The falling-notes view uses the same numbers, so the
// notes fall exactly onto their keys.
export function keyLayout(low = 36, high = 96) {
  let whites = 0;
  for (let p = low; p <= high; p++) if (!isBlack(p)) whites++;
  const w = 100 / whites;
  const keys = new Map();
  let wi = 0;
  for (let p = low; p <= high; p++) {
    if (isBlack(p)) keys.set(p, { left: wi * w - w * 0.3, width: w * 0.6, black: true });
    else { keys.set(p, { left: wi * w, width: w, black: false }); wi++; }
  }
  return keys;
}

export class Keyboard {
  constructor(el, { low = 36, high = 96, onPress = null, onRelease = null, compact = false } = {}) {
    this.el = el;
    this.low = low;
    this.high = high;
    this.keys = new Map();
    this.onPress = onPress;
    this.onRelease = onRelease;
    el.classList.add("kb");
    if (compact) el.classList.add("kb-compact");
    this._build();
  }

  _build() {
    this.layout = keyLayout(this.low, this.high);
    for (let p = this.low; p <= this.high; p++) {
      const g = this.layout.get(p);
      const key = document.createElement("div");
      key.dataset.pitch = p;
      const label = document.createElement("span");
      label.className = "kb-label";
      label.textContent = labelText(p);
      key.appendChild(label);
      key.style.left = `${g.left}%`;
      key.style.width = `${g.width}%`;
      if (g.black) {
        key.className = "kb-key kb-black";
      } else {
        key.className = "kb-key kb-white";
        if (p === MIDDLE_C) {
          const dot = document.createElement("span");
          dot.className = "kb-middle-c";
          dot.title = "Middle C";
          key.appendChild(dot);
        }
      }
      if (this.onPress) {
        key.addEventListener("pointerdown", (e) => {
          e.preventDefault();
          key.setPointerCapture(e.pointerId);
          this.onPress(p);
        });
        const up = () => this.onRelease && this.onRelease(p);
        key.addEventListener("pointerup", up);
        key.addEventListener("pointercancel", up);
      }
      this.el.appendChild(key);
      this.keys.set(p, key);
    }
  }

  setDown(pitch, down) {
    const k = this.keys.get(pitch);
    if (k) k.classList.toggle("down", down);
  }

  setHeld(pitch, held) {
    // Released key that still sounds because the pedal is down.
    const k = this.keys.get(pitch);
    if (k) k.classList.toggle("held", held);
  }

  mark(pitch, cls, on = true) {
    const k = this.keys.get(pitch);
    if (k) k.classList.toggle(cls, on);
  }

  // Give exactly these pitches the class. Only keys that change are touched (60 fps loop).
  setMarked(cls, pitches) {
    this._marks ||= new Map();
    const prev = this._marks.get(cls) || new Set();
    const next = new Set(pitches);
    for (const p of prev) if (!next.has(p)) this.mark(p, cls, false);
    for (const p of next) if (!prev.has(p)) this.mark(p, cls, true);
    this._marks.set(cls, next);
  }

  clear(cls = "down") {
    for (const k of this.keys.values()) k.classList.remove(cls);
  }

  refreshLabels() {
    for (const [p, k] of this.keys) k.querySelector(".kb-label").textContent = labelText(p);
  }

  showAllNames(show) {
    this.el.classList.toggle("kb-names", show);
  }
}
