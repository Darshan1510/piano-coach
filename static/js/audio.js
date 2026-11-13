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

  play(pitch, seconds = 0.8, velocity = 90) {
    if (!this.ready || !this.running) return;
    this.sampler.triggerAttackRelease(midiToToneName(pitch), seconds, Tone.now(), velocity / 127);
  }
}
