// Songs screen: song cards by level (level, hands, length). Click a card to practice the song.
// Text follows PLAN 7.4: Level 1-2 users see no "bar", "beat", "tempo", "chord" or "rest".

const LEVELS = {
  1: { title: "Level 1: First songs", text: "Use your right hand. Your hand stays in one place most of the time." },
  2: { title: "Level 2: Play with the click", text: "Play at a steady speed. The app can play the left hand for you." },
};

export function handsText(hands) {
  if (hands.length === 1) return hands[0] === "R" ? "Right hand" : "Left hand";
  return "Right hand. The app can play the left hand.";
}

export function lengthText(seconds) {
  if (seconds < 60) return `About ${Math.max(5, Math.round(seconds / 5) * 5)} seconds`;
  const m = Math.round(seconds / 30) / 2;
  return `About ${m} minute${m === 1 ? "" : "s"}`;
}

const ICON_HAND = '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11M11 10.5V4.5a1.5 1.5 0 0 1 3 0V11M14 10.5V6a1.5 1.5 0 0 1 3 0v7a6 6 0 0 1-6 6h-.5a6 6 0 0 1-5-2.7L3.3 13a1.5 1.5 0 0 1 2.4-1.8L8 14"/>';
const ICON_TIME = '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>';
const ICON_NOTES = '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>';

export class SongsScreen {
  constructor(el, { api, onOpen }) {
    this.el = el;
    this.api = api;
    this.onOpen = onOpen;
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
    const levels = [...new Set(this.songs.map((s) => s.level))].sort((a, b) => a - b);
    let first = true;
    for (const level of levels) {
      const info = LEVELS[level] || { title: `Level ${level}`, text: "" };
      const group = document.createElement("section");
      group.className = "song-level";
      group.innerHTML = `<div class="song-level-head"><h2></h2><p class="muted"></p></div><div class="song-grid"></div>`;
      group.querySelector("h2").textContent = info.title;
      group.querySelector("p").textContent = info.text;
      const grid = group.querySelector(".song-grid");
      for (const s of this.songs.filter((x) => x.level === level)) {
        grid.appendChild(this._card(s, first));
        first = false;
      }
      el.appendChild(group);
    }
  }

  _card(s, first) {
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
    card.querySelector(".m-hands").textContent = handsText(s.hands);
    card.querySelector(".m-time").textContent = lengthText(s.seconds);
    const mine = s.notes_by_hand ? s.notes_by_hand[s.hands.includes("R") ? "R" : s.hands[0]] : s.note_count;
    card.querySelector(".m-notes").textContent = `${mine} notes to play`;
    card.addEventListener("click", () => this.onOpen(s.id));
    return card;
  }
}
