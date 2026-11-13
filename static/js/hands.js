// Hand outline over the keyboard (PLAN 6.5): a half-transparent hand with 5 finger dots on the
// keys of the current hand position. The finger for the next note is bright. One beat before a
// position change: dashed dots on the new keys, an arrow, and the text "Move your right hand to G."

import { isBlack, keyName } from "/static/js/keyboard.js";

const HAND_WORD = { R: "right", L: "left" };

// Keys of fingers 1-5. Same rule as riyaz/songs.py position_keys().
export function handKeys(pos) {
  if (pos.keys) return pos.keys;
  const step = pos.hand === "R" ? 1 : -1;
  const keys = [pos.thumb_pitch];
  let p = pos.thumb_pitch;
  while (keys.length < 5) {
    p += step;
    if (!isBlack(p)) keys.push(p);
  }
  return keys;
}

// Hand positions of one hand, sorted by start.
export function positionsOf(song, hand) {
  return song.hand_positions.filter((p) => p.hand === hand).sort((a, b) => a.start - b.start);
}

// The position at this beat (the first one before the song starts), and the next change.
export function positionAt(list, beat) {
  if (!list.length) return { pos: null, next: null };
  let i = 0;
  while (i + 1 < list.length && list[i + 1].start <= beat + 1e-6) i++;
  return { pos: list[i], next: list[i + 1] || null };
}

// Plain text for a position change (PLAN 6.5, 7.4: show where, use plain words).
export function moveText(from, to) {
  const hand = HAND_WORD[to.hand];
  if (from.thumb_pitch !== to.thumb_pitch) return `Move your ${hand} hand to ${keyName(to.thumb_pitch)}.`;
  const a = handKeys(from);
  const b = handKeys(to);
  for (let f = 4; f >= 0; f--) {
    if (a[f] !== b[f]) return `Spread your ${hand} hand. Finger ${f + 1} goes on ${keyName(b[f])}.`;
  }
  return "";
}

export class HandsView {
  constructor(canvas, layout) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.layout = layout; // Map pitch -> {left %, width %, black}
    this.w = 0;
    this.h = 0;
  }

  resize() {
    const r = this.canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.w = r.width;
    this.h = r.height;
    this.canvas.width = Math.round(r.width * dpr);
    this.canvas.height = Math.round(r.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  _dot(pitch) {
    const g = this.layout.get(pitch);
    if (!g) return null;
    // White keys: below the key letter (CSS .pr-keyboard .kb-label, top 64 %), so the dot does not cover it.
    return { x: ((g.left + g.width / 2) / 100) * this.w, y: this.h * (g.black ? 0.42 : 0.84) };
  }

  // hands: [{hand, pos, next, nextFinger, active, colors}]; returns the move text or "".
  draw(hands, beat, colors, reducedMotion) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.w, this.h);
    let hint = "";
    for (const h of hands) {
      if (!h.pos) continue;
      const color = colors[h.hand];
      const alpha = h.active ? 1 : 0.45;
      const ink = { on: colors.on ? colors.on[h.hand] : "#08111c", edge: colors.dotEdge || "#08111c" };
      this._hand(handKeys(h.pos), color, alpha, h.nextFinger, false, ink);
      // One beat early: show where the hand goes, with an arrow.
      if (h.next && h.next.start - beat <= 1 + 1e-6 && h.next.start > beat - 1e-6) {
        const from = handKeys(h.pos);
        const to = handKeys(h.next);
        this._hand(to, color, alpha * 0.9, 0, true, ink);
        this._arrow(from, to, color, alpha, beat, reducedMotion);
        if (h.active && !hint) hint = moveText(h.pos, h.next);
      }
    }
    return hint;
  }

  // Finger numbers meet WCAG AA (>= 4.5:1): the dots are solid (not half transparent).
  // Next finger: hand color, dark outline, text color for this hand (--on-hand-*).
  // Other fingers: white dot, ring in the hand color, dark text (19:1).
  _hand(keys, color, alpha, nextFinger, ghost, ink) {
    const ctx = this.ctx;
    const dots = keys.map((k) => this._dot(k)).filter(Boolean);
    if (dots.length < 5) return;
    const xs = dots.map((d) => d.x);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const palmTop = this.h * 0.93;
    const r = Math.max(7, Math.min(11, (maxX - minX) / 9));

    if (!ghost) {
      // palm and fingers (half transparent)
      ctx.globalAlpha = 0.22 * alpha;
      ctx.fillStyle = color;
      ctx.beginPath();
      const pad = r * 1.4;
      roundRect(ctx, minX - pad, palmTop, maxX - minX + pad * 2, this.h - palmTop + 12, 12);
      ctx.fill();
      ctx.globalAlpha = 0.35 * alpha;
      ctx.strokeStyle = color;
      ctx.lineWidth = Math.max(4, r * 0.9);
      ctx.lineCap = "round";
      ctx.beginPath();
      for (const d of dots) {
        ctx.moveTo(d.x, palmTop + 4);
        ctx.lineTo(d.x, d.y + r);
      }
      ctx.stroke();
    }

    ctx.font = `700 ${Math.round(r * 1.2)}px -apple-system, BlinkMacSystemFont, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    dots.forEach((d, i) => {
      const finger = i + 1;
      const isNext = !ghost && finger === nextFinger;
      const rr = isNext ? r * 1.3 : r;
      ctx.beginPath();
      ctx.arc(d.x, d.y, rr, 0, Math.PI * 2);
      if (ghost) {
        ctx.globalAlpha = 0.9 * alpha;
        ctx.setLineDash([3, 3]);
        ctx.lineWidth = 2;
        ctx.strokeStyle = color;
        ctx.stroke();
        ctx.setLineDash([]);
      } else {
        ctx.globalAlpha = 1;
        ctx.fillStyle = isNext ? color : "#ffffff";
        ctx.fill();
        ctx.lineWidth = isNext ? 2 : 2.5;
        ctx.strokeStyle = isNext ? ink.edge : color;
        ctx.globalAlpha = isNext ? 1 : Math.max(0.6, alpha);
        ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.fillStyle = isNext ? ink.on : "#08111c";
        ctx.fillText(String(finger), d.x, d.y + 0.5);
      }
    });
    ctx.globalAlpha = 1;
  }

  _arrow(from, to, color, alpha, beat, reducedMotion) {
    const a = this._dot(from[0]);
    const b = this._dot(to[0]);
    const a5 = this._dot(from[4]);
    const b5 = this._dot(to[4]);
    if (!a || !b || !a5 || !b5) return;
    const ctx = this.ctx;
    const x0 = (a.x + a5.x) / 2;
    const x1 = (b.x + b5.x) / 2;
    if (Math.abs(x1 - x0) < 2) return;
    const y = this.h * 0.93;
    // a small move along the arrow (not with reduced motion)
    const wiggle = reducedMotion ? 0 : Math.sin(beat * Math.PI * 4) * 3;
    const dir = Math.sign(x1 - x0);
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 4;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x0, y);
    ctx.lineTo(x1 - dir * 10 + wiggle * dir, y);
    ctx.stroke();
    ctx.beginPath();
    const tip = x1 + wiggle * dir;
    ctx.moveTo(tip, y);
    ctx.lineTo(tip - dir * 14, y - 9);
    ctx.lineTo(tip - dir * 14, y + 9);
    ctx.closePath();
    ctx.fill();
    ctx.globalAlpha = 1;
  }
}

export function roundRect(ctx, x, y, w, h, r) {
  if (ctx.roundRect) ctx.roundRect(x, y, w, h, Math.min(r, w / 2, h / 2));
  else ctx.rect(x, y, w, h);
}
