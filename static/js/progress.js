// Progress page (PLAN 3 Pro, 9.4): skill radar, practice calendar, results over time per song.
// Inline SVG, no libraries. Colors come from CSS tokens (dark and light). Each chart has a table
// with the same numbers (screen readers, and people who do not read charts).

import { esc } from "/static/js/terms.js";
import { renderCalendar } from "/static/js/today.js";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";

function el(name, attrs = {}, parent = null) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (parent) parent.appendChild(e);
  return e;
}

function title(node, text) {
  el("title", {}, node).textContent = text;
}

function dayText(day) {
  const d = new Date(`${day}T12:00:00`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export class ProgressScreen {
  constructor({ api, terms }) {
    this.api = api;
    this.terms = terms;
    this.data = null;
    $("pg-song").addEventListener("change", () => this._renderSong());
  }

  async show() {
    try {
      this.data = await this.api("/api/progress");
    } catch {
      return;
    }
    this.render();
  }

  render() {
    const d = this.data;
    if (!d) return;
    this._renderSkills(d.skills);
    const st = d.habit.streak;
    $("pg-streak").textContent = `${st.days} day${st.days === 1 ? "" : "s"} in a row. Today: ${Math.floor(d.habit.today_minutes)} of ${d.habit.goal_minutes} minutes.`;
    renderCalendar($("pg-calendar"), d.habit.calendar, d.today);
    this._renderReviews(d.reviews, d.today);
    const sel = $("pg-song");
    const keep = sel.value;
    sel.innerHTML = "";
    for (const s of d.songs) sel.appendChild(new Option(s.title, s.song_id));
    if (!d.songs.length) sel.appendChild(new Option("No results yet", ""));
    if (keep && d.songs.some((s) => s.song_id === keep)) sel.value = keep;
    this._renderSong();
  }

  _name(text) {
    return this.terms ? this.terms.plainText(text) : text;
  }

  // ---------------------------------------------------------------- skill radar

  _renderSkills(skills) {
    const box = $("pg-radar");
    box.innerHTML = "";
    // The view box has room for the labels on all sides (labels must not touch the card edge).
    const W = 440;
    const H = 330;
    const cx = W / 2;
    const cy = H / 2;
    const R = 108;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "pg-radar-svg", role: "img",
      "aria-label": "Your skills as a picture. The table next to it has the same numbers." }, box);
    const n = skills.length;
    const pt = (i, v) => {
      const a = -Math.PI / 2 + (2 * Math.PI * i) / n;
      return [cx + Math.cos(a) * R * v, cy + Math.sin(a) * R * v];
    };
    for (const ring of [0.25, 0.5, 0.75, 1]) {
      el("polygon", { points: skills.map((_, i) => pt(i, ring).join(",")).join(" "), class: "pg-ring" }, svg);
    }
    skills.forEach((s, i) => {
      const [x, y] = pt(i, 1);
      el("line", { x1: cx, y1: cy, x2: x, y2: y, class: "pg-axis" }, svg);
      const [lx, ly] = pt(i, 1.12);
      const t = el("text", { x: lx, y: ly, class: `pg-label${s.value === null ? " none" : ""}`,
        "text-anchor": Math.abs(lx - cx) < 8 ? "middle" : lx < cx ? "end" : "start", "dominant-baseline": "middle" }, svg);
      t.textContent = this._name(s.name);
    });
    const vals = skills.map((s, i) => pt(i, (s.value || 0) / 100));
    const empty = skills.every((s) => s.value === null);
    box.classList.toggle("is-empty", empty);
    if (empty) {
      const note = document.createElement("p");
      note.className = "pg-radar-empty";
      note.textContent = "Play a song to see your skills here.";
      box.appendChild(note);
    }
    el("polygon", { points: vals.map((p) => p.join(",")).join(" "), class: "pg-area" }, svg);
    skills.forEach((s, i) => {
      if (s.value === null) return;
      const [x, y] = vals[i];
      const g = el("g", { class: "pg-dot", tabindex: 0 }, svg);
      el("circle", { cx: x, cy: y, r: 12, class: "pg-hit" }, g); // hit target larger than the mark
      el("circle", { cx: x, cy: y, r: 4.5, class: "pg-mark" }, g);
      title(g, `${this._name(s.name)}: ${Math.round(s.value)} of 100`);
    });
    const body = $("pg-skill-table").querySelector("tbody");
    body.innerHTML = "";
    for (const s of skills) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(this._name(s.name))}</td><td class="pg-level">${s.value === null
        ? '<span class="muted" aria-hidden="true">—</span><span class="sr-only">No results yet</span>'
        : `<span class="pg-bar"><i style="width:${s.value}%"></i></span><b>${Math.round(s.value)}</b>`}</td><td>${s.n}</td>`;
      body.appendChild(tr);
    }
    $("pg-skill-note").classList.toggle("hidden", !skills.some((s) => s.value === null));
  }

  // ---------------------------------------------------------------- spaced repetition list

  _renderReviews(list, today) {
    const ul = $("pg-reviews");
    ul.innerHTML = "";
    if (!list.length) {
      ul.innerHTML = '<li class="muted">When you learn a song, the app asks you to play its parts again after a few days.</li>';
      return;
    }
    for (const r of list.slice(0, 8)) {
      const li = document.createElement("li");
      const what = r.kind === "drill" ? "Find the key" : `${r.part || "The song"} of "${r.title}"`;
      const when = r.due <= today ? "Today" : dayText(r.due);
      li.innerHTML = `<span>${esc(what)}</span><span class="chip${r.due <= today ? " chip-ok" : ""}">${esc(when)}</span>`;
      ul.appendChild(li);
    }
  }

  // ---------------------------------------------------------------- results over time

  _renderSong() {
    const box = $("pg-chart");
    const body = $("pg-run-table").querySelector("tbody");
    box.innerHTML = "";
    body.innerHTML = "";
    const song = this.data && this.data.songs.find((s) => s.song_id === $("pg-song").value);
    if (!song) {
      box.innerHTML = '<p class="muted pg-empty">Play a song. Your results show here.</p>';
      return;
    }
    const pts = song.points.slice(-40);
    const W = 640;
    const H = 230;
    const m = { l: 40, r: 16, t: 14, b: 28 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "pg-chart-svg", role: "img",
      "aria-label": `Results of "${song.title}" over time. The table below has the same numbers.` }, box);
    const x = (i) => m.l + (pts.length < 2 ? (W - m.l - m.r) / 2 : (i * (W - m.l - m.r)) / (pts.length - 1));
    const y = (v) => m.t + ((100 - v) * (H - m.t - m.b)) / 100;
    for (const v of [0, 50, 100]) {
      el("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "pg-grid" }, svg);
      const t = el("text", { x: m.l - 8, y: y(v), class: "pg-tick", "text-anchor": "end", "dominant-baseline": "middle" }, svg);
      t.textContent = String(v);
    }
    // The goal line: a song is done at 80 (PLAN 8.3).
    el("line", { x1: m.l, x2: W - m.r, y1: y(80), y2: y(80), class: "pg-goal" }, svg);
    const gt = el("text", { x: W - m.r, y: y(80) - 6, class: "pg-tick", "text-anchor": "end" }, svg);
    gt.textContent = "Goal 80";
    const series = [
      { mode: "play", cls: "s1", label: "Play along: points" },
      { mode: "wait", cls: "s2", label: "Play: keys right the first time (%)" },
    ];
    for (const s of series) {
      const idx = pts.map((p, i) => [p, i]).filter(([p]) => p.mode === s.mode);
      if (idx.length > 1) {
        el("polyline", { points: idx.map(([p, i]) => `${x(i)},${y(p.value)}`).join(" "), class: `pg-line ${s.cls}` }, svg);
      }
      for (const [p, i] of idx) {
        const g = el("g", { class: "pg-dot", tabindex: 0 }, svg);
        el("circle", { cx: x(i), cy: y(p.value), r: 11, class: "pg-hit" }, g);
        if (s.mode === "play") el("circle", { cx: x(i), cy: y(p.value), r: 4.5, class: `pg-mark ${s.cls}` }, g);
        else el("rect", { x: x(i) - 4, y: y(p.value) - 4, width: 8, height: 8, class: `pg-mark ${s.cls}` }, g);
        title(g, `${dayText(p.day)}: ${Math.round(p.value)} (${s.label}), speed ${Math.round((p.speed || 1) * 100)}%`);
      }
    }
    const legend = document.createElement("div");
    legend.className = "pg-legend";
    legend.innerHTML = series.map((s) => `<span><i class="pg-key ${s.cls}"></i>${esc(s.label)}</span>`).join("");
    box.appendChild(legend);
    for (const p of [...pts].reverse().slice(0, 12)) {
      const tr = document.createElement("tr");
      const what = p.whole ? "Whole song" : p.section !== null && p.section !== undefined ? `Part ${p.section + 1}` : "A short place";
      tr.innerHTML = `<td>${esc(dayText(p.day))}</td><td>${p.mode === "play" ? "Play along" : "Play"}</td>
        <td><b>${Math.round(p.value)}</b>${p.mode === "play" ? " points" : "%"}</td><td>${Math.round((p.speed || 1) * 100)}%</td><td>${esc(what)}</td>`;
      body.appendChild(tr);
    }
  }
}
