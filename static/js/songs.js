// Songs screen: song cards by level (level, hands, length). Click a card to practice the song.
// Text follows PLAN 7.4: Level 1-2 users see no "bar", "beat", "tempo", "chord" or "rest".

const LEVELS = {
  1: { title: "Level 1: First songs", text: "Use your right hand. Your hand stays in one place most of the time." },
  2: { title: "Level 2: Play with the click", text: "Play at a steady speed. The app can play the left hand for you." },
  3: { title: "Level 3: The left hand joins", text: "Play with your left hand. Then play with both hands." },
  4: { title: "Level 4: Move and black keys", text: "Move your hand to new places. Play your first black key." },
  5: { title: "Level 5: Keys together", text: "Your left hand plays 3 keys together." },
  6: { title: "Level 6: Patterns that repeat", text: "The same few groups of keys come again and again." },
  7: { title: "Level 7: Longer runs", text: "Play more than 5 keys in a row." },
  8: { title: "Level 8: Rhythm patterns", text: "Your left hand plays patterns, with two rhythms from Indian music." },
};

export function handsText(hands, source = "builtin", level = 1) {
  if (hands.length === 1) return hands[0] === "R" ? "Right hand" : "Left hand";
  if (source !== "builtin" || level === 3 || level >= 5) return "Right hand and left hand";
  return "Right hand. The app can play the left hand.";
}

export function lengthText(seconds) {
  if (seconds < 60) return `About ${Math.max(5, Math.round(seconds / 5) * 5)} seconds`;
  const m = Math.round(seconds / 30) / 2;
  return `About ${m} minute${m === 1 ? "" : "s"}`;
}

const ICON_HAND = '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10.5V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v7a6 6 0 0 1-6 6h-.5a6 6 0 0 1-5-2.7L3.3 13a1.5 1.5 0 0 1 2.4-1.8L8 14"/>';
const ICON_TIME = '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>';
const ICON_OK = '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>';
const ICON_NEED = '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/>';
const ICON_NOTES = '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>';

export class SongsScreen {
  constructor(el, { api, onOpen, onImport, onEasy, onEdit }) {
    this.el = el;
    this.api = api;
    this.onOpen = onOpen;
    this.onImport = onImport;
    this.onEasy = onEasy;
    this.onEdit = onEdit;
    this.songs = [];
  }

  async load() {
    try {
      this.songs = (await this.api("/api/songs")).songs;
    } catch {
      this.songs = [];
    }
    this.render();
    return this.songs;
  }

  render() {
    const el = this.el;
    el.innerHTML = "";
    if (!this.songs.length) {
      el.innerHTML = '<div class="card"><p class="muted">The app cannot find songs. Start the app again.</p></div>';
      return;
    }
    const builtin = this.songs.filter((s) => s.source === "builtin" || !s.source);
    const mine = this.songs.filter((s) => s.source && s.source !== "builtin");
    const levels = [...new Set(builtin.map((s) => s.level))].sort((a, b) => a - b);
    let first = true;
    for (const level of levels) {
      const info = LEVELS[level] || { title: `Level ${level}`, text: "" };
      const group = document.createElement("section");
      group.className = "song-level";
      group.innerHTML = `<div class="song-level-head"><h2></h2><p class="muted"></p></div><div class="song-grid"></div>`;
      group.querySelector("h2").textContent = info.title;
      group.querySelector("p").textContent = info.text;
      const grid = group.querySelector(".song-grid");
      for (const s of builtin.filter((x) => x.level === level)) {
        grid.appendChild(this._card(s, first));
        first = false;
      }
      el.appendChild(group);
    }
    // The user's imported songs (Phase 3a): one group, with the difficulty text on each card.
    const group = document.createElement("section");
    group.className = "song-level song-level-mine";
    group.innerHTML = `<div class="song-level-head"><h2>Your songs</h2><p class="muted"></p></div><div class="song-grid"></div>`;
    group.querySelector("p").textContent = mine.length
      ? "Songs that you imported, easy versions and your copies. Each card tells you what the song needs."
      : "Import a MIDI or audio file of a song that you like. The app adds it here.";
    const grid = group.querySelector(".song-grid");
    // An easy version comes just after its song.
    const order = [];
    const versions = mine.filter((s) => s.version_of && mine.some((m) => m.id === s.version_of.id));
    for (const s of mine) {
      if (versions.includes(s)) continue;
      order.push(s);
      for (const v of versions) if (v.version_of.id === s.id) order.push(v);
    }
    for (const s of order) grid.appendChild(this._card(s, false));
    if (!mine.length) {
      const empty = document.createElement("article");
      empty.className = "card song-empty";
      empty.innerHTML = '<p class="muted">You have no imported songs.</p><button class="btn song-import-empty">Import a song</button>';
      empty.querySelector("button").addEventListener("click", () => this.onImport && this.onImport());
      grid.appendChild(empty);
    }
    el.appendChild(group);
  }

  _card(s, first) {
    return songCard(s, first, () => this.onOpen(s.id), {
      onEasy: this.onEasy && (() => this.onEasy(s.version_of ? s.version_of.id : s.id)),
      onEdit: this.onEdit && (() => this.onEdit(s.id)),
      onOpenEasy: (id) => this.onOpen(id),
    });
  }
}

// One song card. Imported songs show the difficulty text (PLAN 8.4) and "Your song".
// actions (Phase 5a): onEasy (make an easy version), onEdit (song editor), onOpenEasy(id).
export function songCard(s, first, onOpen, actions = {}) {
  const card = document.createElement("article");
  card.className = `card song-card${first ? " song-card-first" : ""}`;
  card.dataset.song = s.id;
  card.innerHTML = `
    <div class="song-card-top">
      <span class="pill pill-level">Level ${s.level}</span>
      ${first ? '<span class="card-eyebrow song-start">Start here</span>' : ""}
    </div>
    <h3 class="song-title"></h3>
    <ul class="song-meta">
      <li><svg class="icon" viewBox="0 0 24 24">${ICON_HAND}</svg><span class="m-hands"></span></li>
      <li><svg class="icon" viewBox="0 0 24 24">${ICON_TIME}</svg><span class="m-time"></span></li>
      <li><svg class="icon" viewBox="0 0 24 24">${ICON_NOTES}</svg><span class="m-notes"></span></li>
    </ul>
    <button class="btn ${first ? "primary" : ""} song-open">Practice</button>`;
  card.querySelector(".song-title").textContent = s.title;
  card.querySelector(".m-hands").textContent = handsText(s.hands, s.source, s.level);
  card.querySelector(".m-time").textContent = lengthText(s.seconds);
  const imported = s.source && s.source !== "builtin";
  const mine = imported ? s.note_count
    : (s.notes_by_hand ? s.notes_by_hand[s.hands.includes("R") ? "R" : s.hands[0]] : s.note_count);
  card.querySelector(".m-notes").textContent = `${mine} notes to play`;
  if (imported) {
    card.querySelector(".song-card-top").insertAdjacentHTML("beforeend", '<span class="pill pill-quiet pill-mine">Your song</span>');
    if (s.version_of) {
      card.querySelector(".pill-mine").textContent = "Easy version";
      const of = document.createElement("p");
      of.className = "song-of muted";
      of.textContent = `An easy version of "${s.version_of.title}".${s.version_of.changed_text ? ` ${s.version_of.changed_text}` : ""}`;
      card.querySelector(".song-title").after(of);
    }
    if (s.difficulty) {
      const ok = s.difficulty.playable || s.difficulty.easy;
      const need = document.createElement("p");
      need.className = `song-need${ok ? " ok" : ""}`;
      need.innerHTML = `<svg class="icon" viewBox="0 0 24 24">${ok ? ICON_OK : ICON_NEED}</svg><span></span>`;
      need.querySelector("span").textContent = s.difficulty.text;
      card.querySelector(".song-meta").after(need);
    }
  }
  const row = document.createElement("div");
  row.className = "song-actions";
  const open = card.querySelector(".song-open");
  open.replaceWith(row);
  row.appendChild(open);
  if (s.easy && actions.onOpenEasy) {
    open.classList.remove("primary");
    const b = document.createElement("button");
    b.className = "btn primary song-easy-open";
    b.textContent = "Play the easy version";
    b.addEventListener("click", (e) => { e.stopPropagation(); actions.onOpenEasy(s.easy.id); });
    row.prepend(b);
  }
  // Small links under the buttons: easy version and the editor (Phase 5a).
  const links = document.createElement("div");
  links.className = "song-links";
  if (imported && actions.onEasy && !(s.difficulty && s.difficulty.playable && !s.version_of)) {
    const b = document.createElement("button");
    b.className = "btn btn-ghost btn-sm song-make-easy";
    b.textContent = s.version_of ? "Other easy version" : "Make an easy version";
    b.addEventListener("click", (e) => { e.stopPropagation(); actions.onEasy(); });
    links.appendChild(b);
  }
  if (actions.onEdit) {
    const b = document.createElement("button");
    b.className = "btn btn-ghost btn-sm song-edit";
    b.textContent = "Edit the notes";
    b.title = imported ? "Open the song in the editor" : "Open a copy of the song in the editor";
    b.addEventListener("click", (e) => { e.stopPropagation(); actions.onEdit(); });
    links.appendChild(b);
  }
  if (links.children.length) row.after(links);
  card.addEventListener("click", onOpen);
  return card;
}
