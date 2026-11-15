// Free-play recorder (Phase 6, riyaz/recorder.py): record what the user plays, play it back on
// the Mac (Tone.js, here) or, only when the user selects it, on the keyboard speaker (the server
// sends the notes), save it as a MIDI file, or open it as a song (the MIDI importer).
//
// Saving: in the app window the native web view ignores <a download>, so the page asks Python
// for a Save dialog (window.pywebview.api.save_recording, main.py; same as DocKit). In a browser
// the link downloads the file.

import { esc } from "/static/js/terms.js";

const $ = (id) => document.getElementById(id);

function lengthText(s) {
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m ? `${m} min ${sec} s` : `${sec} s`;
}

export class RecorderPanel {
  constructor({ link, api, piano, getStatus, startSound, onSong }) {
    this.link = link;
    this.api = api;
    this.piano = piano;
    this.getStatus = getStatus;
    this.startSound = startSound;
    this.onSong = onSong;
    this.state = { recording: false, playing: null };
    this.list = [];
    this.timers = [];
    this.macPlaying = null;
    $("rec-start").addEventListener("click", () => this.start());
    $("rec-stop").addEventListener("click", () => this.stop());
    $("rec-stop-play").addEventListener("click", () => this.stopPlayback());
    link.on("recorder", (s) => { this.state = s; this.render(); if (s.saved) this.load(); });
    this.tick = setInterval(() => { if (this.state.recording) this._status(); }, 500);
  }

  async load() {
    try {
      const r = await this.api("/api/recorder");
      this.state = r;
      this.list = r.recordings;
    } catch { /* the next load shows them */ }
    this.render();
  }

  _say(text) { $("rec-msg").textContent = text; }

  _status() {
    const s = this.state;
    const el = $("rec-status");
    if (s.recording) {
      el.className = "pill pill-bad";
      el.textContent = `Recording: ${lengthText(s.seconds + (performance.now() - (this._t0 || performance.now())) / 1000)}`;
    } else if (s.playing || this.macPlaying) {
      el.className = "pill pill-level";
      el.textContent = "Playing";
    } else {
      el.className = "pill";
      el.textContent = "Not recording";
    }
  }

  render() {
    const s = this.state;
    if (s.recording && !this._t0) this._t0 = performance.now();
    if (!s.recording) this._t0 = null;
    $("rec-start").classList.toggle("hidden", !!s.recording);
    $("rec-stop").classList.toggle("hidden", !s.recording);
    $("rec-stop-play").classList.toggle("hidden", !(s.playing || this.macPlaying));
    this._status();
    const ul = $("rec-list");
    ul.innerHTML = "";
    if (!this.list.length) {
      ul.innerHTML = '<li class="muted">No recordings yet.</li>';
      return;
    }
    const canKb = !!(this.getStatus().output);
    for (const r of this.list) {
      const li = document.createElement("li");
      li.className = "rec-item";
      const when = r.created.replace("T", " ").slice(0, 16);
      li.innerHTML = `<div class="rec-info"><b>${esc(r.title)}</b><span class="muted">${esc(when)} · ${lengthText(r.seconds)} · ${r.notes} keys</span></div>
        <div class="btn-row rec-buttons">
          <button class="btn btn-sm" data-act="mac">Play on the Mac</button>
          ${canKb ? '<button class="btn btn-sm" data-act="kb">Play on the keyboard</button>' : ""}
          <a class="btn btn-sm" data-act="save" href="/api/recordings/${encodeURIComponent(r.id)}/midi" download="${esc(r.id)}.mid">Save as MIDI file</a>
          <button class="btn btn-sm" data-act="song">Open as a song</button>
          <button class="btn btn-sm btn-ghost" data-act="del">Delete</button>
        </div>`;
      li.addEventListener("click", (e) => {
        const b = e.target.closest("[data-act]");
        if (b) this._act(b.dataset.act, r, e);
      });
      ul.appendChild(li);
    }
  }

  async start() {
    this.stopMac();
    try {
      this.state = await this.api("/api/recorder/start", {});
      this._say("Play now. Click \"Stop\" at the end.");
    } catch (err) { this._say(err.message); }
    this.render();
  }

  async stop() {
    try {
      const s = await this.api("/api/recorder/stop", {});
      this.state = s;
      this._say(s.saved ? `The app saved "${s.saved.title}".` : "You played no keys. The app did not save a recording.");
    } catch (err) { this._say(err.message); }
    await this.load();
  }

  // The user leaves Free play: the Mac playback stops; a running recording stops and is saved
  // (the server keeps it in the list), so that no recording runs where the user cannot see it.
  hide() {
    this.stopMac();
    if (this.state.recording) this.stop();
  }

  stopMac() {
    this.timers.forEach(clearTimeout);
    this.timers = [];
    if (this.macPlaying) this.piano.releaseAll();
    this.macPlaying = null;
  }

  async stopPlayback() {
    this.stopMac();
    if (this.state.playing) this.state = await this.api("/api/recorder/stop-playback", {}).catch(() => this.state);
    this.render();
  }

  async _playMac(r) {
    await this.stopPlayback();
    if (this.startSound) await this.startSound().catch(() => {});
    const rec = await this.api(`/api/recordings/${encodeURIComponent(r.id)}`);
    this.macPlaying = r.id;
    let pedal = false;
    const held = new Set();
    for (const [t, kind, a, b] of rec.events) {
      this.timers.push(setTimeout(() => {
        if (kind === "on") { held.delete(a); this.piano.noteOn(a, b); }
        else if (kind === "off") { if (pedal) held.add(a); else this.piano.noteOff(a); }
        else if (a === 64) {
          pedal = b >= 64;
          if (!pedal) { for (const p of held) this.piano.noteOff(p); held.clear(); }
        }
      }, t * 1000));
    }
    const end = rec.events.length ? rec.events[rec.events.length - 1][0] : 0;
    this.timers.push(setTimeout(() => { this.macPlaying = null; this.piano.releaseAll(); this.render(); }, end * 1000 + 800));
    this.render();
  }

  async _act(act, r, e) {
    try {
      if (act === "mac") return await this._playMac(r);
      if (act === "kb") {
        this.stopMac();
        this.state = await this.api(`/api/recordings/${encodeURIComponent(r.id)}/play-keyboard`, {});
        return this.render();
      }
      if (act === "save") {
        if (!window.pywebview || !window.pywebview.api) return; // a browser: the link downloads the file
        e.preventDefault();
        const res = await window.pywebview.api.save_recording(r.id);
        if (res.ok) this._say(`The app saved the MIDI file: ${res.path}`);
        else if (!res.cancelled) this._say(`The app cannot save the file: ${res.error}`);
        return;
      }
      if (act === "song") {
        const res = await this.api(`/api/recordings/${encodeURIComponent(r.id)}/import`, {});
        this._say(`The app made the song "${res.song.title}". Find it in Songs.`);
        if (this.onSong) this.onSong(res.song.id);
        return undefined;
      }
      if (act === "del") {
        await this.api(`/api/recordings/${encodeURIComponent(r.id)}/delete`, {});
        this._say(`The app deleted "${r.title}".`);
        return await this.load();
      }
    } catch (err) {
      this._say(err.message);
    }
    return undefined;
  }
}
