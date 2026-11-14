// Mac sound: Tone.js Sampler with local Salamander Grand Piano samples (CC-BY 3.0).
// WKWebView keeps the AudioContext "suspended" until a click, so start() must run in a click handler.

const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

function sampleUrls() {
  // Samples exist for A, C, D#, F# in octaves 1-7, and C8. File names use "s" for "#".
  const urls = {};
  for (let o = 1; o <= 7; o++) {
    for (const n of ["A", "C", "D#", "F#"]) urls[`${n}${o}`] = `${n.replace("#", "s")}${o}.mp3`;
  }
  urls["C8"] = "C8.mp3";
  return urls;
}

export function midiToToneName(pitch) {
  return NAMES[pitch % 12] + (Math.floor(pitch / 12) - 1);
}

export class Piano {
  constructor() {
    this.ready = false;
    this.started = false;
    this.sampler = null;
  }

  // Call from a click handler.
  async start() {
    if (!window.Tone) return false;
    await Tone.start();
    this.started = Tone.context.state === "running";
    if (!this.sampler) {
      this.sampler = new Tone.Sampler({
        urls: sampleUrls(),
        baseUrl: "/static/samples/salamander/",
        release: 1,
        onload: () => { this.ready = true; },
      }).toDestination();
    }
    return this.started;
  }

  get running() {
    return !!window.Tone && Tone.context.state === "running";
  }

  noteOn(pitch, velocity = 80) {
    if (!this.ready || !this.running) return;
    this.sampler.triggerAttack(midiToToneName(pitch), Tone.now(), velocity / 127);
  }

  noteOff(pitch) {
    if (!this.ready || !this.running) return;
    this.sampler.triggerRelease(midiToToneName(pitch), Tone.now());
  }

  // ---- song playback (Phase 2). Times are AudioContext seconds (audioNow() + delay).

  // Context time now, without the Tone.js look-ahead (Tone.now() adds about 0.1 s).
  audioNow() {
    return window.Tone ? Tone.context.currentTime : 0;
  }

  playAt(pitch, when, seconds, velocity = 80) {
    if (!this.ready || !this.running) return;
    this.sampler.triggerAttackRelease(midiToToneName(pitch), Math.max(0.05, seconds), when, velocity / 127);
  }

  // The delay of the sound output (seconds), when the browser gives it (AudioContext.outputLatency;
  // Tone.js 15 does not wrap it). 0 when unknown or not sane.
  outputLatency() {
    const raw = window.Tone && Tone.context ? Tone.context.rawContext : null;
    const v = raw && typeof raw.outputLatency === "number" ? raw.outputLatency : 0;
    return v > 0 && v < 0.5 ? v : 0;
  }

  // The click (metronome). A higher, louder click on the first of each group. The click starts
  // outputLatency() early, so that the user hears it at `when` (PLAN 4 Timing).
  clickAt(when, accent = false) {
    if (!this.running) return;
    when = Math.max(this.audioNow(), when - this.outputLatency());
    if (!this.click) {
      this.click = new Tone.Synth({
        oscillator: { type: "triangle" },
        envelope: { attack: 0.001, decay: 0.05, sustain: 0, release: 0.02 },
        volume: -6,
      }).toDestination();
    }
    this.click.triggerAttackRelease(accent ? "C7" : "G6", 0.03, when, accent ? 1 : 0.6);
  }

  releaseAll() {
    if (this.sampler && this.ready) this.sampler.releaseAll();
  }

  play(pitch, seconds = 0.8, velocity = 90) {
    if (!this.ready || !this.running) return;
    this.sampler.triggerAttackRelease(midiToToneName(pitch), seconds, Tone.now(), velocity / 127);
  }
}
