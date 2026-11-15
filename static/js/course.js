// Learn (the song ladder, PLAN 8.3) and Words (the glossary, PLAN 7.4 Rule 4).
// Texts from data/course/ are shown with the unlocked terms underlined (terms.markup).

import { esc } from "/static/js/terms.js";
import { lengthText } from "/static/js/songs.js";

const ICON_OK = '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>';
const ICON_LOCK = '<svg class="icon" viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>';
const ICON_STAR = '<svg class="icon" viewBox="0 0 24 24"><path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/></svg>';

export function handsWords(hands) {
  if (hands.length > 1) return "Both hands";
  return hands[0] === "L" ? "Left hand" : "Right hand";
}

export class LearnScreen {
  constructor(el, { api, terms, modal, onOpenSong, onBasics }) {
    this.el = el;
    this.api = api;
    this.terms = terms;
    this.modal = modal;
    this.onOpenSong = onOpenSong;
    this.onBasics = onBasics;
    this.state = null;
  }

  async load() {
    try {
      this.state = await this.api("/api/course");
    } catch {
      this.state = null;
    }
    this.render();
    return this.state;
  }

  render() {
    const st = this.state;
    const el = this.el;
    el.innerHTML = "";
    if (!st) {
      el.innerHTML = '<div class="card"><p class="muted">The app cannot load the course. Start the app again.</p></div>';
      return;
    }
    const T = this.terms;
    // Keyboard basics
    const b = document.createElement("section");
    b.className = `card learn-basics${st.basics.done ? "" : " card-hero-soft"}`;
    const doneTasks = st.basics.steps.flatMap((s) => s.tasks).filter((t) => t.done).length;
    const allTasks = st.basics.steps.flatMap((s) => s.tasks).length;
    b.innerHTML = `<div class="card-head"><h3>Keyboard basics</h3>
        <span class="pill ${st.basics.done ? "pill-ok" : "pill-warn"}">${st.basics.done ? "Done" : `${doneTasks} of ${allTasks} done`}</span></div>
      <p class="muted">Three short steps on your keyboard: find your way, fingers and hand shape, read the screen. About 10 minutes.</p>
      <button class="btn ${st.basics.done ? "" : "primary"} btn-lg">${st.basics.done ? "Do keyboard basics again" : "Do keyboard basics"}</button>`;
    b.querySelector("button").addEventListener("click", () => this.onBasics());
    el.appendChild(b);

    const rule = document.createElement("p");
    rule.className = "muted learn-rule";
    rule.innerHTML = `${ICON_STAR}<span>A song is done when you play the whole song at ${st.rule.speed}% speed and press ${st.rule.score}% or more of the keys right the first time. A level is done when all its songs are done.</span>`;
    el.appendChild(rule);

    if (st.all_done) {
      const done = document.createElement("div");
      done.className = "card learn-all-done";
      done.innerHTML = `<h3>You finished all levels in this version.</h3><p class="muted">Play your songs again, or import a song that you like.</p>`;
      el.appendChild(done);
    }

    for (const lv of st.levels) {
      const sec = document.createElement("section");
      sec.className = `learn-level${lv.current ? " is-current" : ""}${lv.open ? "" : " is-locked"}${lv.done ? " is-done" : ""}`;
      sec.dataset.level = lv.level;
      const pill = lv.done ? `<span class="pill pill-ok">${ICON_OK}Done</span>`
        : lv.current ? '<span class="pill pill-level">You are here</span>'
          : lv.open ? "" : `<span class="pill pill-quiet">${ICON_LOCK}Later</span>`;
      const skills = lv.songs.flatMap((s) => s.skills);
      sec.innerHTML = `
        <div class="learn-level-head">
          <div class="learn-level-num" aria-hidden="true">${lv.level}</div>
          <div class="learn-level-title"><h2>Level ${lv.level}: ${esc(lv.title)}</h2><p class="muted">${T.markup(lv.text)}</p></div>
          <div class="learn-level-side">${pill}<div class="learn-meter" role="img" aria-label="${lv.done_count} of ${lv.songs.length} songs done"><i style="width:${(100 * lv.done_count) / lv.songs.length}%"></i></div><span class="muted learn-count">${lv.done_count} of ${lv.songs.length} songs done</span></div>
        </div>
        <div class="learn-skills"><span class="learn-skills-label">New skills</span>${skills.map((k) => `<span class="chip${k.done ? " chip-ok" : ""}">${k.done ? ICON_OK : ""}${esc(k.name)}</span>`).join("")}</div>
        <div class="learn-songs"></div>`;
      const box = sec.querySelector(".learn-songs");
      for (const s of lv.songs) {
        const card = document.createElement("article");
        card.className = `card learn-song${s.current ? " is-current" : ""}${s.done ? " is-done" : ""}`;
        card.dataset.song = s.song_id;
        const best = s.best !== null && s.best !== undefined ? `Best: ${Math.round(s.best)}%` : s.runs ? "Not done yet" : "New";
        card.innerHTML = `<div class="learn-song-top">${s.done ? `<span class="pill pill-ok">${ICON_OK}Done</span>` : s.current ? '<span class="card-eyebrow">Next song</span>' : "<span></span>"}<span class="muted learn-best">${best}</span></div>
          <h3></h3><p class="muted learn-song-meta">${handsWords(s.hands)} · ${lengthText(s.seconds)}</p>
          ${s.task_text ? `<p class="learn-task">${T.markup(s.task_text)}</p>` : ""}
          <button class="btn ${s.current ? "primary" : ""}">${s.done ? "Play again" : "Practice"}</button>`;
        card.querySelector("h3").textContent = s.title;
        card.querySelector("button").addEventListener("click", (e) => { e.stopPropagation(); this.open(lv, s); });
        box.appendChild(card);
      }
      if (!lv.open) {
        const skip = document.createElement("button");
        skip.className = "btn btn-ghost learn-skip";
        skip.textContent = `Skip to Level ${lv.level}`;
        skip.addEventListener("click", () => this.skip(lv.level));
        sec.querySelector(".learn-level-side").appendChild(skip);
      }
      el.appendChild(sec);
    }
  }

  async open(lv, s) {
    if (!lv.open) {
      const ok = await this.skip(lv.level);
      if (!ok) return;
    }
    // Phase 6 tasks: a lead sheet (play along, own left hand) or the song in a new key family.
    if (s.task === "lead") return this.onOpenSong(s.song_id, { returnTo: "learn", preset: { mode: "play", lead: true } });
    if (s.task === "transpose") {
      const info = await this.api(`/api/songs/${encodeURIComponent(s.song_id)}/keys`).catch(() => null);
      if (info && info.versions.length) {
        return this.onOpenSong(info.versions[0].id, { returnTo: "learn", preset: { mode: "wait", hands: s.hands } });
      }
      return this.onOpenSong(s.song_id, { returnTo: "learn", preset: { mode: "wait", hands: s.hands, newKey: true } });
    }
    this.onOpenSong(s.song_id, { returnTo: "learn", preset: { mode: "wait", hands: s.hands } });
  }

  // PLAN 8.3: the user can skip forward. The app warns which skills the songs need.
  async skip(level) {
    const info = await this.api(`/api/course/skip/${level}`);
    const items = [...(info.basics ? ["The keyboard basics"] : []), ...info.needed];
    const html = items.length
      ? `<p>The songs of Level ${level} need skills that you did not learn yet:</p><ul class="modal-list">${items.map((n) => `<li>${esc(n)}</li>`).join("")}</ul><p class="muted">You can go back to the earlier levels at any time.</p>`
      : `<p>You know the skills for Level ${level}.</p>`;
    const r = await this.modal.show({
      eyebrow: "Skip forward", title: `Go to Level ${level}?`, html, tone: items.length ? "warn" : "",
      buttons: [{ id: "cancel", label: "Stay here" }, { id: "go", label: `Go to Level ${level}`, primary: true }],
    });
    if (r !== "go") return false;
    await this.api("/api/course/skip", { level });
    await this.load();
    return true;
  }
}

export class WordsScreen {
  constructor(el, { terms, onBasics }) {
    this.el = el;
    this.terms = terms;
    this.onBasics = onBasics;
  }

  render() {
    const T = this.terms;
    const el = this.el;
    const known = T.known;
    el.innerHTML = `
      <p class="screen-intro muted">These are the music words that you know. Click "Show me" to see and hear an example. In the app, a word with a dotted line opens its card.</p>
      <div class="words-grid"></div>
      <div class="card words-foot">
        <div><h3>Keyboard basics</h3><p class="muted">Do the 3 steps again: find your way, fingers and hand shape, read the screen.</p></div>
        <button class="btn btn-lg" id="words-basics">Do keyboard basics again</button>
      </div>`;
    const grid = el.querySelector(".words-grid");
    if (!known.length) {
      grid.innerHTML = '<div class="card words-empty"><p class="muted">You know no music words yet. Do the keyboard basics first. Each new skill teaches a word.</p></div>';
    }
    for (const t of known) {
      const card = document.createElement("article");
      card.className = "card word-card";
      card.dataset.term = t.id;
      card.innerHTML = `<div class="word-top"><h3></h3><span class="pill pill-level">Level ${t.level}</span></div>
        <p class="word-text"></p><button class="btn btn-sm">Show me</button>`;
      card.querySelector("h3").textContent = t.term[0].toUpperCase() + t.term.slice(1);
      card.querySelector(".word-text").innerHTML = T.markup(t.card);
      card.querySelector("button").addEventListener("click", () => T.showCard(t.id));
      grid.appendChild(card);
    }
    if (T.lockedCount) {
      const more = document.createElement("p");
      more.className = "muted words-more";
      more.textContent = `You learn ${T.lockedCount} more words in the next levels.`;
      grid.after(more);
    }
    el.querySelector("#words-basics").addEventListener("click", () => this.onBasics());
  }
}
