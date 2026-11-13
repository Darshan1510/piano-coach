// On-screen keyboard: 61 keys (MIDI 36-96), like the YPT-320.

const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const BLACK = new Set([1, 3, 6, 8, 10]);
export const MIDDLE_C = 60;

export function noteName(pitch) {
  return NAMES[pitch % 12];
}

export function isBlack(pitch) {
  return BLACK.has(pitch % 12);
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
    const whites = [];
    for (let p = this.low; p <= this.high; p++) if (!isBlack(p)) whites.push(p);
    const w = 100 / whites.length;
    let wi = 0;
    for (let p = this.low; p <= this.high; p++) {
      const key = document.createElement("div");
      key.dataset.pitch = p;
      const label = document.createElement("span");
      label.className = "kb-label";
      label.textContent = noteName(p);
      key.appendChild(label);
      if (isBlack(p)) {
        key.className = "kb-key kb-black";
        key.style.left = `${wi * w - w * 0.3}%`;
        key.style.width = `${w * 0.6}%`;
      } else {
        key.className = "kb-key kb-white";
        key.style.left = `${wi * w}%`;
        key.style.width = `${w}%`;
        wi++;
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

  clear(cls = "down") {
    for (const k of this.keys.values()) k.classList.remove(cls);
  }

  showAllNames(show) {
    this.el.classList.toggle("kb-names", show);
  }
}
