// Import screen (PLAN 11.1, Phase 3a): select a MIDI file, select the tracks, swap the hands,
// fix the timing (Off, Large steps = 1/8, Small steps = 1/16), import. The file goes to the app with one POST (the bytes of the
// file, not a form): /api/import/midi. The choices go with a second POST.
// Audio (PLAN 11.3, Phase 5a): select an MP3, WAV or M4A file; the app finds the notes in the
// background (/api/import/audio, then the page asks for the progress), makes the song and the easy
// version, and the page opens the result in the song editor.
// Words (PLAN 7.4): "keys together", "speed", "the click"; no locked words.

import { songCard } from "/static/js/songs.js";

const $ = (id) => document.getElementById(id);

export class ImportScreen {
  constructor({ api, onOpen, onEdit }) {
    this.api = api;
    this.onOpen = onOpen;
    this.onEdit = onEdit || (() => {});
    this.job = null; // the audio import that runs (its id)
    this.audio = null; // /api/import/audio: is the audio import in this app?
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
    $("ia-pick").addEventListener("click", () => { if (!$("ia-pick").disabled) $("ia-file").click(); });
    $("ia-file").addEventListener("change", (e) => {
      const f = e.target.files && e.target.files[0];
      e.target.value = "";
      if (f) this.uploadAudio(f);
    });
    $("ia-cancel").addEventListener("click", () => this.cancelAudio());
    $("ia-another").addEventListener("click", () => { this.reset(); $("ia-file").click(); });
  }

  // The screen keeps its state until "Cancel" or a new file.
  async show() {
    if (this.audio) return;
    try {
      this.audio = await this.api("/api/import/audio");
    } catch {
      this.audio = { available: false, text: "The app cannot import audio files now." };
    }
    $("ia-pick").disabled = !this.audio.available;
    $("ia-missing").textContent = this.audio.text || "";
    $("ia-missing").classList.toggle("hidden", !!this.audio.available);
    if (this.audio.available) $("ia-limit").textContent = `${this.audio.max_mb} MB or less and ${this.audio.max_minutes} minutes or less`;
  }

  reset() {
    this.info = null;
    this.selected.clear();
    this.swap = false;
    $("im-options").classList.add("hidden");
    $("im-done").classList.add("hidden");
    if (!this.job) { $("ia-progress").classList.add("hidden"); $("ia-pick").disabled = !(this.audio && this.audio.available); }
    $("ia-done").classList.add("hidden");
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
      box.appendChild(songCard(r.song, false, () => this.onOpen(r.song.id), { onEdit: () => this.onEdit(r.song.id) }));
      if (r.easy) box.appendChild(songCard(r.easy, false, () => this.onOpen(r.easy.id), { onEdit: () => this.onEdit(r.easy.id) }));
      $("im-done-text").textContent = r.easy
        ? "The app also made an easy version for your level (the second card)."
        : "";
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

// ------------------------------------------------------------------ audio import (Phase 5a)

const AUDIO_RE = /\.(mp3|wav|m4a)$/i;
const STAGES = ["load", "notes", "speed", "song"];

ImportScreen.prototype.uploadAudio = async function uploadAudio(file) {
  if (this.job) return;
  this.reset();
  $("im-file-name").textContent = file.name;
  $("im-file-name").classList.remove("hidden");
  if (!AUDIO_RE.test(file.name)) {
    this._error("Select an MP3, WAV or M4A file.");
    return;
  }
  const max = (this.audio && this.audio.max_mb) || 40;
  if (file.size > max * 1024 * 1024) {
    this._error(`The file is too large. The limit is ${max} MB. Select a smaller file.`);
    return;
  }
  $("ia-pick").disabled = true;
  $("im-pick").disabled = true;
  this._progress({ stage: "save", stage_text: "Send the file to the app", progress: 0 });
  $("ia-progress").classList.remove("hidden");
  $("ia-progress").scrollIntoView({ block: "nearest" });
  try {
    const res = await fetch(`/api/import/audio?name=${encodeURIComponent(file.name)}`, {
      method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `The app cannot read the file (error ${res.status}).`);
    this.job = data.id;
    this.started = performance.now();
    this._poll();
  } catch (e) {
    this._audioEnd();
    this._error(e.message || "The app cannot read the file. Try again.");
  }
};

ImportScreen.prototype._poll = async function _poll() {
  const id = this.job;
  if (!id) return;
  let job;
  try {
    job = await this.api(`/api/import/audio/${encodeURIComponent(id)}`);
  } catch (e) {
    this._audioEnd();
    this._error(e.message);
    return;
  }
  if (this.job !== id) return;
  this._progress(job);
  if (job.state === "running") {
    this.pollTimer = setTimeout(() => this._poll(), 400);
    return;
  }
  this._audioEnd();
  if (job.state === "done") this._audioDone(job);
  else this._error(job.error || "The app cannot import this file.");
};

ImportScreen.prototype._progress = function _progress(job) {
  const i = STAGES.indexOf(job.stage);
  for (const li of document.querySelectorAll("#ia-steps li")) {
    const k = STAGES.indexOf(li.dataset.stage);
    li.className = i < 0 ? "" : k < i ? "done" : k === i ? "now" : "";
  }
  // The share of the work: read 5%, notes 80%, speed 5%, song 10%.
  const share = { save: 0, convert: 2, load: 3, notes: 5, speed: 85, song: 90, done: 100 };
  const width = { notes: 80, load: 2 };
  const pct = Math.min(100, Math.round((share[job.stage] ?? 0) + (width[job.stage] || 0) * (job.progress || 0)));
  $("ia-bar-fill").style.width = `${pct}%`;
  document.querySelector(".ia-bar").setAttribute("aria-valuenow", String(pct));
  const secs = this.started ? Math.round((performance.now() - this.started) / 1000) : 0;
  $("ia-status").textContent = `${job.stage_text || ""}${job.stage === "notes" ? ` (${pct}%)` : ""}. Time: ${secs} seconds.`;
};

ImportScreen.prototype._audioEnd = function _audioEnd() {
  clearTimeout(this.pollTimer);
  this.job = null;
  $("ia-progress").classList.add("hidden");
  $("ia-pick").disabled = !(this.audio && this.audio.available);
  $("im-pick").disabled = false;
};

ImportScreen.prototype.cancelAudio = async function cancelAudio() {
  const id = this.job;
  if (!id) return;
  await this.api(`/api/import/audio/${encodeURIComponent(id)}/cancel`, {}).catch(() => {});
};

ImportScreen.prototype._audioDone = function _audioDone(job) {
  const box = $("ia-cards");
  box.innerHTML = "";
  const target = job.easy || job.song;
  for (const s of [job.easy, job.song].filter(Boolean)) {
    box.appendChild(songCard(s, false, () => this.onOpen(s.id), { onEdit: () => this.onEdit(s.id) }));
  }
  const mins = Math.floor((job.duration || 0) / 60);
  const secs = Math.round((job.duration || 0) % 60);
  $("ia-facts").textContent = `The app found ${job.note_count} notes in ${mins ? `${mins} min ` : ""}${secs} s of music, in ${Math.round(job.seconds || 0)} seconds.`
    + (job.easy ? " The first card is the easy version for your level." : "");
  $("ia-edit").onclick = () => this.onEdit(target.id);
  $("ia-done").classList.remove("hidden");
  $("ia-done").scrollIntoView({ block: "nearest" });
  $("ia-edit").focus();
  this.lastJob = job;
};
