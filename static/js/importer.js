// Import screen (PLAN 11.1, Phase 3a): select a MIDI file, select the tracks, swap the hands,
// fix the timing (Off, Large steps = 1/8, Small steps = 1/16), import. The file goes to the app with one POST (the bytes of the
// file, not a form): /api/import/midi. The choices go with a second POST.
// Words (PLAN 7.4): "keys together", "speed", "the click"; no locked words.

import { songCard } from "/static/js/songs.js";

const $ = (id) => document.getElementById(id);

export class ImportScreen {
  constructor({ api, onOpen }) {
    this.api = api;
    this.onOpen = onOpen;
    this.info = null; // the answer of the first POST (token, tracks, title)
    this.selected = new Set();
    this.swap = false;
    this.grid = 0;
    $("im-pick").addEventListener("click", () => $("im-file").click());
    $("im-file").addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (f) this.upload(f);
    });
    $("im-swap").addEventListener("click", () => { this.swap = !this.swap; this._renderTracks(); });
    for (const b of document.querySelectorAll("#im-grid .seg")) {
      b.addEventListener("click", () => {
        this.grid = Number(b.dataset.grid);
        for (const x of document.querySelectorAll("#im-grid .seg")) x.setAttribute("aria-checked", String(x === b));
      });
    }
    $("im-go").addEventListener("click", () => this.finish());
    $("im-cancel").addEventListener("click", () => this.reset());
    $("im-another").addEventListener("click", () => { this.reset(); $("im-file").click(); });
  }

  show() { /* the screen keeps its state until "Cancel" or a new file */ }

  reset() {
    this.info = null;
    this.selected.clear();
    this.swap = false;
    $("im-options").classList.add("hidden");
    $("im-done").classList.add("hidden");
    $("im-file-name").classList.add("hidden");
    this._error("");
    $("im-pick").classList.add("primary");
  }

  _error(text) {
    $("im-error").textContent = text;
    $("im-error").classList.toggle("hidden", !text);
  }

  async upload(file) {
    this.reset();
    $("im-file-name").textContent = file.name;
    $("im-file-name").classList.remove("hidden");
    if (!/\.(mid|midi)$/i.test(file.name)) {
      this._error("This file is not a MIDI file. Select a file that ends in .mid or .midi.");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      this._error("The file is too large. The limit is 2 MB. Select a smaller file.");
      return;
    }
    $("im-pick").disabled = true;
    try {
      const res = await fetch(`/api/import/midi?name=${encodeURIComponent(file.name)}`, {
        method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `The app cannot read the file (error ${res.status}).`);
      this.info = data;
    } catch (e) {
      this._error(e.message || "The app cannot read the file. Try again.");
      return;
    } finally {
      $("im-pick").disabled = false;
    }
    this.selected = new Set(this.info.tracks.filter((t) => t.default).map((t) => t.index));
    $("im-title").value = this.info.title || "";
    this.grid = 0;
    for (const x of document.querySelectorAll("#im-grid .seg")) x.setAttribute("aria-checked", String(x.dataset.grid === "0"));
    $("im-pick").classList.remove("primary");
    $("im-options").classList.remove("hidden");
    this._renderTracks();
    $("im-options").scrollIntoView({ block: "nearest" });
  }

  _order() {
    // The selected tracks in file order. With 2 tracks: the first is the right hand (swap: the left).
    return this.info.tracks.filter((t) => this.selected.has(t.index)).map((t) => t.index);
  }

  _renderTracks() {
    const box = $("im-tracks");
    box.innerHTML = '<div class="im-track head"><span></span><span>Track</span><span>Instrument</span><span>Hand</span><span class="t-count">Notes</span></div>';
    const order = this._order();
    const two = order.length === 2;
    for (const t of this.info.tracks) {
      const row = document.createElement("label");
      row.className = "im-track";
      row.dataset.track = String(t.index);
      row.innerHTML = '<input type="checkbox"><span class="t-name"></span><span class="t-inst"></span><span class="t-hand"></span><span class="t-count"></span>';
      const cb = row.querySelector("input");
      cb.checked = this.selected.has(t.index);
      cb.setAttribute("aria-label", `Use the track ${t.name}`);
      cb.addEventListener("change", () => {
        if (cb.checked) this.selected.add(t.index); else this.selected.delete(t.index);
        this._renderTracks();
      });
      row.querySelector(".t-name").textContent = t.name;
      row.querySelector(".t-inst").textContent = t.drums ? "Drums (not for piano)" : t.instrument;
      row.querySelector(".t-count").textContent = String(t.note_count);
      const hand = row.querySelector(".t-hand");
      if (cb.checked && two) {
        const right = (order[0] === t.index) !== this.swap;
        hand.innerHTML = `<span class="hand-${right ? "R" : "L"}"></span>`;
        hand.firstChild.textContent = right ? "Right hand" : "Left hand";
      } else if (cb.checked) {
        hand.textContent = "Both hands";
      } else {
        hand.textContent = "—";
      }
      box.appendChild(row);
    }
    let text;
    if (order.length === 0) text = "Select one or more tracks.";
    else if (two) text = "The first track is for the right hand. The second track is for the left hand.";
    else text = "The app puts the low notes in the left hand and the high notes in the right hand.";
    if (two && this.swap) text = "The first track is for the left hand. The second track is for the right hand.";
    $("im-hands-text").textContent = text;
    $("im-swap").classList.toggle("hidden", !two);
    $("im-go").disabled = order.length === 0;
  }

  async finish() {
    if (!this.info) return;
    const parts = this._order();
    if (!parts.length) return;
    $("im-go").disabled = true;
    this._error("");
    try {
      const r = await this.api(`/api/import/midi/${encodeURIComponent(this.info.token)}/song`, {
        parts, swap: parts.length === 2 && this.swap, quantize: this.grid || null, title: $("im-title").value.trim(),
      });
      $("im-options").classList.add("hidden");
      $("im-done").classList.remove("hidden");
      const box = $("im-card");
      box.innerHTML = "";
      box.appendChild(songCard(r.song, false, () => this.onOpen(r.song.id)));
      box.querySelector(".song-open").classList.add("primary");
      $("im-done").scrollIntoView({ block: "nearest" });
      box.querySelector(".song-open").focus();
    } catch (e) {
      this._error(e.message);
    } finally {
      $("im-go").disabled = false;
    }
  }
}
