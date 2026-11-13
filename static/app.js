// Riyaz UI: app shell (sidebar + top bar), home, free play keyboard, setup and calibration, settings.

import { Link } from "/static/js/ws.js";
import { Piano } from "/static/js/audio.js";
import { Keyboard, MIDDLE_C, noteName } from "/static/js/keyboard.js";

const $ = (id) => document.getElementById(id);
const link = new Link();
const piano = new Piano();
window.riyaz = { link, piano }; // for manual checks in the web inspector

let status = { connected: false, calibration: {} };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

// ------------------------------------------------------------------ navigation
// The one list of sidebar items. A later phase adds a screen here (and a <section id="screen-ID">
// in index.html). Add only screens that work. group "bottom" = lower part of the sidebar.

const ICONS = {
  home: '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/>',
  play: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M7 6v7M12 6v7M17 6v7"/>',
  setup: '<path d="M9 7V3M15 7V3"/><path d="M6 7h12v4a6 6 0 0 1-12 0z"/><path d="M12 17v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  about: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
};

const NAV = [
  { id: "home", label: "Home", icon: "home" },
  { id: "play", label: "Free play", icon: "play" },
  { id: "setup", label: "Setup", icon: "setup" },
  { id: "settings", label: "Settings", icon: "settings", group: "bottom" },
  { id: "about", label: "About", icon: "about", group: "bottom" },
];

function buildNav() {
  for (const item of NAV) {
    const b = document.createElement("button");
    b.className = "nav-item";
    b.dataset.screen = item.id;
    b.title = item.label;
    b.innerHTML = `<svg class="icon" viewBox="0 0 24 24">${ICONS[item.icon]}</svg><span class="nav-label">${item.label}</span>`;
    b.addEventListener("click", () => show(item.id));
    $(item.group === "bottom" ? "nav-bottom" : "nav").appendChild(b);
  }
}
buildNav();

let current = null;
function show(screen) {
  current = screen;
  for (const el of document.querySelectorAll(".screen")) el.classList.add("hidden");
  $(`screen-${screen}`).classList.remove("hidden");
  for (const b of document.querySelectorAll(".nav-item")) b.classList.toggle("active", b.dataset.screen === screen);
  $("page-title").textContent = NAV.find((n) => n.id === screen)?.label || "";
  if (screen === "about") updateDelayText();
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Error");
  return data;
}

// ------------------------------------------------------------------ theme (dark default, kept in localStorage)

function storageGet(key) { try { return localStorage.getItem(key); } catch { return null; } }
function storageSet(key, value) { try { localStorage.setItem(key, value); } catch { /* blocked: not kept */ } }

function setTheme(theme) {
  document.documentElement.dataset.theme = theme;
  storageSet("riyaz.theme", theme);
  $("theme-btn").title = theme === "dark" ? "Change to light theme" : "Change to dark theme";
  for (const b of document.querySelectorAll("[data-theme-choice]")) {
    b.setAttribute("aria-checked", String(b.dataset.themeChoice === theme));
  }
}
setTheme(storageGet("riyaz.theme") === "light" ? "light" : "dark");
$("theme-btn").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
for (const b of document.querySelectorAll("[data-theme-choice]")) b.addEventListener("click", () => setTheme(b.dataset.themeChoice));

// ------------------------------------------------------------------ sound

async function startSound() {
  const ok = await piano.start();
  $("sound-text").textContent = ok ? "Sound is on" : "Click to turn on sound";
  $("sound-btn").classList.toggle("on", ok);
}
$("sound-btn").addEventListener("click", startSound);
// The first click anywhere also turns on sound (WKWebView needs a user gesture).
document.addEventListener("pointerdown", () => { if (!piano.started) startSound(); }, { once: true });

// ------------------------------------------------------------------ celebration

const CONFETTI_COLORS = ["--accent", "--ok", "--warn", "--hand-right", "--hand-left"];

function celebrate(anchor) {
  if (reducedMotion.matches || !anchor || anchor.offsetParent === null) return; // only on a visible step
  const box = $("confetti");
  const r = anchor.getBoundingClientRect();
  const x0 = r.left + Math.min(r.width, 240) / 2;
  const y0 = r.top + r.height / 2;
  const css = getComputedStyle(document.documentElement);
  for (let i = 0; i < 26; i++) {
    const p = document.createElement("i");
    const angle = (Math.PI * 2 * i) / 26 + Math.random() * 0.3;
    const dist = 60 + Math.random() * 90;
    p.style.left = `${x0}px`;
    p.style.top = `${y0}px`;
    p.style.background = css.getPropertyValue(CONFETTI_COLORS[i % CONFETTI_COLORS.length]).trim();
    p.style.setProperty("--dx", `${Math.cos(angle) * dist}px`);
    p.style.setProperty("--dy", `${Math.sin(angle) * dist + 40}px`);
    p.style.setProperty("--rot", `${Math.random() * 540 - 270}deg`);
    box.appendChild(p);
  }
  setTimeout(() => { box.innerHTML = ""; }, 900);
}

// ------------------------------------------------------------------ status (top bar, home, sidebar)

function renderStatus(s) {
  status = s;
  const el = $("status");
  el.classList.toggle("on", s.connected);
  el.classList.toggle("off", !s.connected);
  $("status-text").textContent = s.connected ? "Keyboard connected" : "Keyboard not connected";
  el.title = s.connected ? s.port : "";
  renderHome();
  renderCalibSummary();
}

link.on("status", renderStatus);
link.on("link", ({ up }) => {
  if (!up) {
    $("status-text").textContent = "The app is not ready. Wait.";
    $("status").className = "status off";
  }
});

// ------------------------------------------------------------------ home

function renderHome() {
  const c = status.calibration || {};
  const calibrated = !!c.calibrated;

  // Start card: one primary action.
  $("start-eyebrow").textContent = calibrated ? "Ready" : "Start here";
  $("start-title").textContent = calibrated ? "Play freely" : "Set up your keyboard";
  $("start-text").textContent = calibrated
    ? "Press keys on your keyboard. The app shows the name of each key and of keys that you play together."
    : "Do the 5 setup steps one time. Then the app knows your keyboard.";
  $("start-btn").textContent = calibrated ? "Start free play" : "Start the setup";

  // Keyboard card
  $("home-kb-pill").className = `pill ${status.connected ? "pill-ok" : "pill-bad"}`;
  $("home-kb-pill-text").textContent = status.connected ? "Connected" : "Not connected";
  $("home-kb-text").textContent = status.connected
    ? `The app uses this device: ${status.port}.`
    : "Connect the keyboard to the Mac. Then go to Setup and click \"Find my keyboard\".";
  $("home-kb-btn").classList.toggle("hidden", status.connected && calibrated);

  // Calibration card
  $("home-calib-pill").className = `pill ${calibrated ? "pill-ok" : "pill-warn"}`;
  $("home-calib-pill").textContent = calibrated ? "Setup done" : "Setup not done";
  $("tile-middle-c").textContent = calibrated ? "Done" : "Not done";
  $("tile-middle-c").classList.toggle("ok", calibrated);
  $("tile-middle-c-hint").textContent = calibrated ? "The app knows where middle C is." : "Setup step 3 finds it.";
  if (calibrated) {
    const n = Math.abs(c.offset);
    $("tile-offset").textContent = n === 0 ? "None" : `${n} key${n === 1 ? "" : "s"}`;
    $("tile-offset-hint").textContent = n === 0
      ? "Your keyboard sends the correct notes."
      : `Your keyboard sends each note ${n} keys too ${c.offset < 0 ? "high" : "low"}. The app corrects this.`;
  } else {
    $("tile-offset").textContent = "—";
    $("tile-offset-hint").textContent = "The app moves each note by this number of keys.";
  }
  $("tile-channel").textContent = c.channel ? String(c.channel) : "—";
  if (c.velocity_range) {
    $("tile-touch").textContent = `${c.velocity_range[0]} to ${c.velocity_range[1]}`;
    $("tile-touch").classList.add("ok");
    $("tile-touch-hint").textContent = "Your softest and loudest key (the top is 127).";
  } else {
    $("tile-touch").textContent = "Not done";
    $("tile-touch").classList.remove("ok");
    $("tile-touch-hint").textContent = "Setup step 4 measures it.";
  }

  // Sidebar: a dot on "Setup" while the setup is not done.
  const setupNav = document.querySelector('.nav-item[data-screen="setup"]');
  let badge = setupNav.querySelector(".nav-badge");
  if (!calibrated && !badge) {
    badge = document.createElement("span");
    badge.className = "nav-badge";
    badge.title = "Setup not done";
    setupNav.appendChild(badge);
  } else if (calibrated && badge) {
    badge.remove();
  }
}

$("start-btn").addEventListener("click", () => {
  if (status.calibration && status.calibration.calibrated) show("play");
  else { show("setup"); goStep("connect"); }
});
$("home-kb-btn").addEventListener("click", () => { show("setup"); goStep("connect"); });

// ------------------------------------------------------------------ free play

const kb = new Keyboard($("keyboard"), {
  onPress: (p) => { kb.setDown(p, true); piano.play(p); showHeld([p]); },
  onRelease: (p) => { kb.setDown(p, false); showHeld(midiDown()); },
});
kb.showAllNames(true);
$("opt-names").addEventListener("change", (e) => kb.showAllNames(e.target.checked));

const down = new Set();
let pedal = false;
const sounding = new Set(); // released keys that still sound because of the pedal

function midiDown() { return [...down].sort((a, b) => a - b); }

function showHeld(pitches) {
  $("held-names").textContent = pitches.length ? pitches.map(noteName).join("  ") : "—";
}

link.on("note_on", (e) => {
  down.add(e.pitch);
  sounding.delete(e.pitch);
  kb.setHeld(e.pitch, false);
  kb.setDown(e.pitch, true);
  miniKb.setDown(e.pitch, true);
  if ($("opt-mac-sound").checked) piano.noteOn(e.pitch, e.vel);
});

link.on("note_off", (e) => {
  down.delete(e.pitch);
  kb.setDown(e.pitch, false);
  miniKb.setDown(e.pitch, false);
  if (pedal && e.reason !== "disconnect") {
    sounding.add(e.pitch);
    kb.setHeld(e.pitch, true);
  } else if ($("opt-mac-sound").checked) {
    piano.noteOff(e.pitch);
  }
});

link.on("cc", (e) => {
  if (e.control !== 64) return;
  if (e.reason !== "disconnect") $("pedal-box").classList.remove("hidden"); // first real CC 64: show it
  pedal = e.value >= 64;
  $("pedal").textContent = pedal ? "Down" : "Up";
  if (!pedal) {
    for (const p of sounding) {
      kb.setHeld(p, false);
      if ($("opt-mac-sound").checked && !down.has(p)) piano.noteOff(p);
    }
    sounding.clear();
  }
});

// Server sends the held keys and the chord name (riyaz/theory.py) after each key event.
link.on("keys", (e) => {
  showHeld(e.held);
  if (e.chord) {
    $("chord-name").textContent = e.chord.name;
    $("chord-hint").textContent = e.chord.quality === "major" ? "happy sound"
      : e.chord.quality === "minor" ? "sad sound" : "";
  } else {
    $("chord-name").textContent = "—";
    $("chord-hint").textContent = e.held.length && e.held.length < 3 ? "Press 3 or more keys together to see a name." : "";
  }
});

// ------------------------------------------------------------------ setup

const STEPS = ["connect", "test", "middle_c", "touch", "output"];
const passed = new Set(); // steps that passed in this visit of the setup
let step = "connect";

function goStep(s) {
  step = s;
  api("/api/setup/cancel", {}).catch(() => {});
  for (const p of document.querySelectorAll(".step-panel")) p.classList.toggle("hidden", p.dataset.panel !== s);
  for (const li of document.querySelectorAll("#stepper li")) {
    li.classList.toggle("active", li.dataset.step === s);
    li.classList.toggle("done", passed.has(li.dataset.step) && li.dataset.step !== s);
  }
  $("step-back").disabled = s === STEPS[0];
  $("step-next").textContent = s === STEPS.at(-1) ? "Finish" : "Next";
  renderNextButton();
}
for (const li of document.querySelectorAll("#stepper li")) li.addEventListener("click", () => goStep(li.dataset.step));
$("step-back").addEventListener("click", () => goStep(STEPS[Math.max(0, STEPS.indexOf(step) - 1)]));
$("step-next").addEventListener("click", () => {
  const i = STEPS.indexOf(step);
  if (i === STEPS.length - 1) show("play"); else goStep(STEPS[i + 1]);
});

// One primary button at a time: the step's own button until the step passes, then "Next".
function renderNextButton() {
  const ok = passed.has(step);
  $("step-next").classList.toggle("primary", ok);
  const action = document.querySelector(`.step-panel[data-panel="${step}"] .step-action`);
  if (action) action.classList.toggle("primary", !ok);
}

function stepPassed(s, resultId) {
  const first = !passed.has(s);
  passed.add(s);
  const li = document.querySelector(`#stepper li[data-step="${s}"]`);
  if (first && li) {
    li.classList.remove("pop");
    void li.offsetWidth; // restart the animation
    li.classList.add("pop", "done");
  }
  if (s === step) renderNextButton();
  if (first) celebrate($(resultId));
}

function setResult(id, text, kind = "") {
  const el = $(id);
  el.textContent = text;
  el.className = `result ${el.classList.contains("big") ? "big " : ""}${kind}`;
}

// Step 1: find the keyboard
$("find-btn").addEventListener("click", async () => {
  setResult("find-result", "The app looks for your keyboard...");
  const s = await api("/api/ports/find", {});
  renderStatus(s);
  renderPorts(s);
  if (s.connected) {
    setResult("find-result", `The app found your keyboard: ${s.port}. Click "Next".`, "ok");
    stepPassed("connect", "find-result");
  } else if (s.inputs.length > 1) setResult("find-result", "The app found more than 1 device. Select your keyboard below.", "warn");
  else setResult("find-result", "The app cannot find a keyboard. Do the steps again. Make sure that the keyboard is on.", "bad");
});

function renderPorts(s) {
  const box = $("port-list");
  box.innerHTML = "";
  if (s.inputs.length <= 1 && s.connected) return;
  for (const name of s.inputs) {
    const b = document.createElement("button");
    b.textContent = name + (name === s.port ? " (selected)" : "");
    b.className = name === s.port ? "btn primary" : "btn";
    b.addEventListener("click", async () => {
      try {
        const st = await api("/api/ports/select", { name });
        renderStatus(st);
        renderPorts(st);
        setResult("find-result", `The app uses ${name}. Click "Next".`, "ok");
        stepPassed("connect", "find-result");
      } catch (err) {
        setResult("find-result", err.message, "bad");
      }
    });
    box.appendChild(b);
  }
}

// Step 2: test (10 seconds)
let testTimer = null;
$("test-btn").addEventListener("click", async () => {
  clearTimeout(testTimer);
  if (!status.connected) {
    setResult("test-result", "Keyboard not connected. Go back to step 1.", "bad");
    return;
  }
  await api("/api/setup/test", {});
  setResult("test-result", "Press any key.");
  testTimer = setTimeout(() => {
    api("/api/setup/cancel", {});
    setResult("test-result", "The app did not hear a key. Swap the IN and OUT plugs on the keyboard. "
      + "Then set TRANSPOSE to 0 and OCTAVE to 0 on the keyboard. Then click \"Start the test\" again.", "bad");
  }, 10000);
});

link.on("setup", (e) => {
  if (e.step === "test") {
    clearTimeout(testTimer);
    setResult("test-result", "Good. The app hears your keyboard. Click \"Next\".", "ok");
    stepPassed("test", "test-result");
  }
});

// Step 3: middle C
const miniKb = new Keyboard($("mini-keyboard"), { low: 48, high: 72, compact: true });
miniKb.mark(MIDDLE_C, "target");

$("middle-c-btn").addEventListener("click", async () => {
  await api("/api/setup/middle_c", {});
  setResult("middle-c-result", "Press middle C.");
});

// Step 4: touch
function renderDots(count, needed = 8) {
  const box = $("touch-dots");
  box.innerHTML = "";
  for (let i = 0; i < needed; i++) {
    const d = document.createElement("span");
    d.className = `dot-step ${i < count ? "filled" : ""} ${i < 4 ? "soft" : "loud"}`;
    d.textContent = i < 4 ? "soft" : "loud";
    box.appendChild(d);
  }
}
renderDots(0);

$("touch-btn").addEventListener("click", async () => {
  await api("/api/setup/touch", {});
  renderDots(0);
  setResult("touch-result", "Play 4 notes soft.");
});

link.on("calibration", (e) => {
  if (e.step === "middle_c") {
    let text = "Good. The app knows where middle C is.";
    if (e.offset !== 0) {
      const n = Math.abs(e.offset);
      text += ` Your keyboard sends each note ${n} keys too ${e.offset < 0 ? "high" : "low"}. The app corrects this.`;
    }
    setResult("middle-c-result", text + " Click \"Next\".", "ok");
    stepPassed("middle_c", "middle-c-result");
  } else if (e.step === "touch_progress") {
    renderDots(e.count, e.needed);
    setResult("touch-result", e.count < 4 ? "Play 4 notes soft." : "Now play 4 notes loud.");
  } else if (e.step === "touch") {
    renderDots(8);
    if (e.touch_on) {
      setResult("touch-result", "Good. The app knows how soft and how loud you play. Click \"Next\".", "ok");
      stepPassed("touch", "touch-result");
    } else {
      setResult("touch-result", "All notes have the same force. Press the TOUCH button on the keyboard to turn touch on. Then click \"Start\" again.", "bad");
    }
  }
  if (e.step !== "touch_progress") {
    status.calibration = e;
    renderHome();
    renderCalibSummary();
  }
});

// Step 5: output test
$("out-btn").addEventListener("click", async () => {
  const r = await api("/api/output/test-note", {});
  if (!r.ok) {
    setResult("out-result", "The app cannot send notes to this keyboard. You can skip this step.", "warn");
    return;
  }
  $("out-yes").classList.remove("hidden");
  $("out-no").classList.remove("hidden");
  setResult("out-result", "");
});
$("out-yes").addEventListener("click", () => {
  setResult("out-result", "Good. The app can play notes on your keyboard.", "ok");
  stepPassed("output", "out-result");
});
$("out-no").addEventListener("click", () => setResult("out-result",
  "Make sure that the plug marked OUT is in the keyboard's MIDI IN jack. Turn up the volume on the keyboard. Then try again.", "warn"));

function renderCalibSummary() {
  const c = status.calibration || {};
  const parts = [];
  if (c.calibrated) parts.push(`Middle C: done (correction ${c.offset > 0 ? "+" : ""}${c.offset}, channel ${c.channel}).`);
  if (c.velocity_range) parts.push(`Soft and loud: done (${c.velocity_range[0]} to ${c.velocity_range[1]}).`);
  $("calib-summary").textContent = parts.join(" ");
}

// ------------------------------------------------------------------ settings

$("reset-calib").addEventListener("click", async () => {
  const c = await api("/api/calibration/reset", {});
  status.calibration = c;
  passed.clear();
  renderHome();
  renderCalibSummary();
  show("setup");
  goStep("connect");
});

// ------------------------------------------------------------------ about: delay

function updateDelayText() {
  const m = link.medianDelay();
  $("delay-text").textContent = m === null ? "No keys yet." : `${m.toFixed(1)} ms (${link.recentDelays.length} keys)`;
}
setInterval(() => { if (current === "about") updateDelayText(); }, 1000);

// ------------------------------------------------------------------ start

goStep("connect");
renderHome();
api("/api/state").then((s) => {
  renderStatus(s);
  // Home shows the next action. If the setup is not done, the Start card points to it.
  show("home");
}).catch(() => show("home"));
