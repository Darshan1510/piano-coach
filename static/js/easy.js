// "Make an easy version" screen (PLAN 11.2 simplifier, 8.4 easy versions by level, Phase 5a).
// The app makes a new song from a song: the tune in the right hand, and one key or 3 keys
// together in the left hand. The new song is in "Your songs"; the first song does not change.
// Words (PLAN 7.4): "tune", "3 keys together" (not "chord"), "group of clicks" (not "bar"),
// "speed", "fewer black keys"; no locked words.

import { songCard } from "/static/js/songs.js";

const $ = (id) => document.getElementById(id);

export class EasyScreen {
  constructor({ api, onPractice, onEdit, getLevel }) {
    this.api = api;
    this.onPractice = onPractice;
    this.onEdit = onEdit;
    this.getLevel = getLevel || (() => 1);
    this.song = null;
    this.opts = { left: "chords", key: "same", slow: false, change: "bar" };
    for (const group of ["left", "key", "change"]) {
      for (const b of document.querySelectorAll(`#ez-${group} .seg`)) {
        b.addEventListener("click", () => { this.opts[group] = b.dataset.value; this._renderOptions(); });
      }
    }
    $("ez-slow").addEventListener("change", (e) => { this.opts.slow = e.target.checked; });
    $("ez-level").addEventListener("click", () => this.make(true));
    $("ez-make").addEventListener("click", () => this.make(false));
  }

  async open(songId) {
    const song = await this.api(`/api/songs/${encodeURIComponent(songId)}`);
    this.song = song;
    const level = this.getLevel();
    $("ez-song-title").textContent = song.title;
    $("ez-level-text").textContent = `The app makes a version that uses only the skills of your level (Level ${level}).`;
    $("ez-level").textContent = `Make the easy version for Level ${level}`;
    const num = song.time_signature[0];
    const half = num % 2 === 0;
    $("ez-change-bar").textContent = `Every ${num} clicks`;
    $("ez-change-half").textContent = `Every ${num / 2} clicks`;
    $("ez-change-half").disabled = !half;
    if (!half) this.opts.change = "bar";
    $("ez-result").classList.add("hidden");
    this._error("");
    this._renderOptions();
    return song;
  }

  _renderOptions() {
    for (const group of ["left", "key", "change"]) {
      for (const b of document.querySelectorAll(`#ez-${group} .seg`)) b.setAttribute("aria-checked", String(b.dataset.value === this.opts[group]));
    }
    $("ez-change-row").classList.toggle("hidden", this.opts.left === "none");
    $("ez-slow").checked = this.opts.slow;
  }

  _error(text) {
    $("ez-error").textContent = text;
    $("ez-error").classList.toggle("hidden", !text);
  }

  async make(forLevel) {
    if (!this.song) return;
    this._error("");
    const btns = [$("ez-level"), $("ez-make")];
    for (const b of btns) b.disabled = true;
    try {
      const body = forLevel ? { for_level: true } : { ...this.opts };
      const r = await this.api(`/api/songs/${encodeURIComponent(this.song.id)}/simplify`, body);
      const box = $("ez-card");
      box.innerHTML = "";
      box.appendChild(songCard(r.song, false, () => this.onPractice(r.song.id)));
      $("ez-result-text").textContent = r.fits
        ? `The easy version is in "Your songs". You can play it now (Level ${r.song.level}).`
        : `The easy version is in "Your songs". It is a Level ${r.song.level} song. For a version that you can play now, select "Make the easy version for Level ${this.getLevel()}".`;
      $("ez-open-editor").onclick = () => this.onEdit(r.song.id);
      $("ez-result").classList.remove("hidden");
      $("ez-result").scrollIntoView({ block: "nearest" });
      this.result = r;
    } catch (e) {
      this._error(e.message);
    } finally {
      for (const b of btns) b.disabled = false;
    }
  }
}
