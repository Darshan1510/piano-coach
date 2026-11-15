// Riyaz UI: app shell (sidebar + top bar), home, today (daily session), learn (course), songs,
// words, practice, keyboard basics, free play, setup, settings.

import { Link } from "/static/js/ws.js";
import { Piano } from "/static/js/audio.js";
import { Keyboard, MIDDLE_C, WORDS, shortKeyName } from "/static/js/keyboard.js";
import { SongsScreen } from "/static/js/songs.js";
import { PracticeScreen, radioKeys } from "/static/js/practice.js";
import { ImportScreen } from "/static/js/importer.js";
import { Modal, Terms } from "/static/js/terms.js";
import { LearnScreen, WordsScreen } from "/static/js/course.js";
import { BasicsScreen } from "/static/js/basics.js";
import { TodayScreen } from "/static/js/today.js";
import { ProgressScreen } from "/static/js/progress.js";
import { EditorScreen } from "/static/js/editor.js";
import { EasyScreen } from "/static/js/easy.js";
import { IntuitionScreen } from "/static/js/intuition.js";
import { RecorderPanel } from "/static/js/recorder.js";
import { WeekCard, bindCoachSettings } from "/static/js/coach.js";

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
  today: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><path d="M9 15l2 2 4-4"/>',
  learn: '<path d="M4 20h4v-5h4v-5h4V5h4"/><path d="M4 20V16"/>',
  words: '<path d="M5 4h10a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4z"/><path d="M5 16a4 4 0 0 1 4-4h10"/>',
  songs: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
  play: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M7 6v7M12 6v7M17 6v7"/>',
  setup: '<path d="M9 7V3M15 7V3"/><path d="M6 7h12v4a6 6 0 0 1-12 0z"/><path d="M12 17v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  about: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  progress: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  ear: '<path d="M7 9a5 5 0 0 1 10 0c0 3-3 4-3 7a3 3 0 0 1-6 0"/><path d="M10 10a2 2 0 0 1 4 0"/>',
};

const NAV = [
  { id: "home", label: "Home", icon: "home" },
  { id: "today", label: "Today", icon: "today" },
  { id: "learn", label: "Learn", icon: "learn" },
  { id: "songs", label: "Songs", icon: "songs" },
  { id: "intuition", label: "Ear games", icon: "ear" },
  { id: "progress", label: "Progress", icon: "progress" },
  { id: "words", label: "Words", icon: "words" },
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

// Screens that are not in the sidebar: the sidebar item that stays active, and the page title.
const SUB_SCREENS = {
  practice: { nav: "songs", title: "Practice" }, import: { nav: "songs", title: "Import a song" },
  easy: { nav: "songs", title: "Make an easy version" }, editor: { nav: "songs", title: "Song editor" },
  basics: { nav: "learn", title: "Keyboard basics" },
};
const RETURN_NAV = { songs: "songs", today: "today", learn: "learn", basics: "learn" };

let current = null;
function show(screen) {
  if (current === "practice" && screen !== "practice") practice.hide();
  if (current === "basics" && screen !== "basics") basics.hide();
  if (current === "today" && screen !== "today") today.hide();
  if (current === "editor" && screen !== "editor") editor.hide();
  if (current === "intuition" && screen !== "intuition") intuitionScreen.hide();
  if (current === "play" && screen !== "play") recorder.hide(); // a running recording stops and is saved
  if (screen === "practice") SUB_SCREENS.practice.nav = RETURN_NAV[practice.returnTo] || "songs";
  current = screen;
  for (const el of document.querySelectorAll(".screen")) el.classList.add("hidden");
  $(`screen-${screen}`).classList.remove("hidden");
  const navId = SUB_SCREENS[screen]?.nav || screen;
  for (const b of document.querySelectorAll(".nav-item")) b.classList.toggle("active", b.dataset.screen === navId);
  $("page-title").textContent = SUB_SCREENS[screen]?.title || NAV.find((n) => n.id === screen)?.label || "";
  if (screen === "about") updateDelayText();
  if (screen === "settings") { loadHabitSettings(); loadTapSetting(); loadCoachSettings(); loadPedalSetting(); }
  if (screen === "play") recorder.load();
  if (screen === "songs") songsScreen.load();
  if (screen === "practice") practice.show();
  if (screen === "import") importScreen.show();
  if (screen === "editor") editor.show();
  if (screen === "today") today.show();
  if (screen === "learn") learn.load();
  if (screen === "progress") { progressScreen.show(); weekCard.show(); }
  if (screen === "intuition") intuitionScreen.show();
  if (screen === "words") terms.load().then(() => words.render());
  if (screen === "basics") basics.show();
  renderSessionPill();
  $("content").scrollTop = 0;
}

// FastAPI sends a string, or a list of {loc, msg} (422: bad request body). Show plain text.
function errorText(detail, status) {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d && typeof d.msg === "string" ? d.msg : "")).filter(Boolean);
    if (msgs.length) return `The app did not accept the request (${msgs.join("; ")}).`;
  }
  return `The app cannot do this now (error ${status}). Try again.`;
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errorText(data.detail, res.status));
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
new Set([...document.querySelectorAll("[data-theme-choice]")].map((b) => b.parentElement)).forEach(radioKeys);

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

// ------------------------------------------------------------------ songs and practice (Phase 2)

const modal = new Modal();
const terms = new Terms({ api, modal, piano });
let course = null; // course state (/api/course): level, basics, bar lines

const practice = new PracticeScreen({
  link, piano, api, celebrate, reducedMotion, getStatus: () => status, startSound,
  terms, getCourse: () => course, onReturn: (to) => show(to || "songs"), modal,
});
async function openSong(id, opts = {}) {
  try {
    await practice.open(id, opts);
    show("practice");
  } catch (err) {
    console.error(err);
  }
}
// Phase 5a: song editor and easy versions (simplifier).
const editor = new EditorScreen({
  api, piano, startSound, getCourse: () => course,
  onPractice: (id) => openSong(id), onBack: () => show("songs"),
});
async function openEditor(id) {
  try {
    await editor.open(id);
    show("editor");
  } catch (err) {
    console.error(err);
  }
}
const easy = new EasyScreen({
  api, onPractice: openSong, onEdit: openEditor, getLevel: () => (course ? course.user_level : 1),
});
async function openEasy(id) {
  try {
    await easy.open(id);
    show("easy");
  } catch (err) {
    console.error(err);
  }
}
$("ez-back").addEventListener("click", () => show("songs"));
for (const id of ["#ez-left", "#ez-key", "#ez-change", "#ed-grid"]) radioKeys(document.querySelector(id));
const songsScreen = new SongsScreen($("song-list"), {
  api, onOpen: openSong, onImport: () => show("import"), onEasy: openEasy, onEdit: openEditor,
});
const importScreen = new ImportScreen({ api, onOpen: openSong, onEdit: openEditor });
window.riyaz.editor = editor;
window.riyaz.easy = easy;
$("songs-import").addEventListener("click", () => show("import"));
$("im-back").addEventListener("click", () => show("songs"));
new Set([...document.querySelectorAll("#im-grid")]).forEach(radioKeys);
window.riyaz.practice = practice; // for checks (frame rate) in the web inspector
window.riyaz.importScreen = importScreen;
window.riyaz.show = show;

// ------------------------------------------------------------------ course, daily session, habit (Phase 3b)

const learn = new LearnScreen($("learn-body"), {
  api, terms, modal, onOpenSong: openSong, onBasics: () => show("basics"),
});
const words = new WordsScreen($("words-body"), { terms, onBasics: () => show("basics") });
const basics = new BasicsScreen({
  link, api, piano, terms, reducedMotion, celebrate,
  onPractice: (id) => openSong(id, { returnTo: "basics", preset: { mode: "wait", hands: ["R"], speed: 1 } }),
  onDone: () => { loadCourse(); celebrate($("basics-done")); },
});
$("basics-to-today").addEventListener("click", () => show("today"));
let sessionText = null;
const today = new TodayScreen({
  link, api, piano, terms, reducedMotion, celebrate, openSong, showScreen: show,
  onHabit: (h) => renderHabit(h),
  onTick: (text) => { sessionText = text; renderSessionPill(); },
});
window.riyaz.today = today;
const progressScreen = new ProgressScreen({ api, terms });
// Phase 6: the weekly summary (Progress), the coach switch (Settings), the recorder (Free play).
const weekCard = new WeekCard({ api, terms });
const loadCoachSettings = bindCoachSettings(api);
const recorder = new RecorderPanel({ link, api, piano, getStatus: () => status, startSound, onSong: (id) => openSong(id) });
window.riyaz.recorder = recorder;
// Phase 5b: intuition exercises (PLAN 10), the "Ear" page.
const intuitionScreen = new IntuitionScreen({
  link, api, piano, terms, reducedMotion, celebrate, getStatus: () => status, onLearn: () => show("learn"),
});
window.riyaz.intuition = intuitionScreen;
window.riyaz.progress = progressScreen;
window.riyaz.learn = learn;
window.riyaz.basics = basics;
window.riyaz.terms = terms;
window.riyaz.modal = modal;

async function loadCourse() {
  try {
    course = await api("/api/course");
  } catch { return course; }
  today.setCourse(course);
  practice.refreshWords();
  renderHome();
  return course;
}

function renderSessionPill() {
  const show_ = !!sessionText && current !== "today";
  $("session-pill").classList.toggle("hidden", !show_);
  if (show_) $("session-pill-text").textContent = `Today: ${sessionText}`;
}
$("session-pill").addEventListener("click", () => show("today"));

let habit = null;
function renderHabit(h) {
  habit = h;
  const n = h.streak.days;
  $("streak-text").textContent = `${n} day${n === 1 ? "" : "s"}`;
  $("streak-pill").classList.toggle("lit", n > 0);
  $("streak-pill").title = h.streak.freeze_left
    ? "Days in a row with practice. You have 1 free day this week."
    : "Days in a row with practice. You used the free day of this week.";
  $("minutes-text").textContent = `${Math.floor(h.today_minutes)} min today`;
  $("minutes-pill").classList.toggle("met", h.today_minutes >= h.goal_minutes);
  $("minutes-pill").title = `Practice time today. Your daily goal is ${h.goal_minutes} minutes.`;
  renderHome();
}
async function refreshHabit() {
  try { renderHabit(await api("/api/habit")); } catch { /* the next refresh shows it */ }
}
setInterval(refreshHabit, 30000);

// Course events (riyaz/server.py): a song run was saved. A level is done: celebrate.
link.on("course", async (e) => {
  if (e.event !== "run") return;
  const before = course ? course.level : null;
  await loadCourse();
  refreshHabit();
  if (e.unlocked && e.unlocked.length) { await terms.load(); await terms.firstUse(e.unlocked); }
  if (e.level_up && before !== null) {
    celebrate($("page-title"));
    const next = e.level <= course.max_level ? `Now start Level ${e.level}.` : "You finished all levels in this version.";
    // PLAN 8.4: the user's songs have a new easy version for the new level.
    const esc = (t) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const fresh = (e.new_versions || []).map((v) => `<p>${esc(v.text)}</p>`).join("");
    const choice = await modal.show({ eyebrow: "Level done", title: `Level ${e.level_before} is done!`, tone: "party",
      html: `<p>You finished all the songs of Level ${e.level_before}. ${next}</p>${fresh}`,
      buttons: [...(e.new_versions && e.new_versions.length ? [{ id: "songs", label: "Show my songs" }] : []),
        { id: "ok", label: "Great", primary: true }] });
    if (choice === "songs") show("songs");
  }
});

// ------------------------------------------------------------------ settings: daily practice

async function loadHabitSettings() {
  const st = await api("/api/settings/habit").catch(() => null);
  if (!st) return;
  for (const b of document.querySelectorAll("#set-length .seg")) b.setAttribute("aria-checked", String(Number(b.dataset.min) === st.session_minutes));
  $("set-goal").value = String(st.goal_minutes);
  $("set-notify").checked = st.notify;
  $("set-notify-time").value = st.notify_time;
  const sel = $("set-song");
  const list = await api("/api/songs").catch(() => ({ songs: [] }));
  sel.innerHTML = "";
  sel.appendChild(new Option("The next song of the course", ""));
  for (const s of list.songs) sel.appendChild(new Option(s.source === "builtin" ? s.title : `${s.title} (your song)`, s.id));
  sel.value = st.song_id || "";
}
async function saveHabit(body) {
  await api("/api/settings/habit", body).catch(() => {});
  loadHabitSettings();
  refreshHabit();
}
for (const b of document.querySelectorAll("#set-length .seg")) b.addEventListener("click", () => saveHabit({ session_minutes: Number(b.dataset.min) }));
$("set-goal").addEventListener("change", (e) => saveHabit({ goal_minutes: Number(e.target.value) }));
$("set-song").addEventListener("change", (e) => saveHabit({ song_id: e.target.value || null }));
$("set-notify").addEventListener("change", (e) => saveHabit({ notify: e.target.checked }));
$("set-notify-time").addEventListener("change", (e) => saveHabit({ notify_time: e.target.value }));
$("set-notify-test").addEventListener("click", async () => {
  const r = await api("/api/habit/notify-test", {}).catch(() => ({ ok: false }));
  $("set-notify-test").textContent = r.ok ? "Reminder sent" : "The Mac did not show it";
});
for (const g of ["#set-length", "#today-length"]) radioKeys(document.querySelector(g));

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
  practice.onStatus();
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
  const mins = habit ? habit.session_minutes : 20;
  const basicsDone = !!(course && course.basics.done);
  $("start-eyebrow").textContent = calibrated ? (habit && habit.streak.today_done ? "Good work today" : "Ready") : "Start here";
  $("start-title").textContent = calibrated ? "Start today's practice" : "Set up your keyboard";
  $("start-text").textContent = calibrated
    ? (basicsDone
      ? `About ${mins} minutes: a warm-up, your song, a review and a key game.`
      : `About ${mins} minutes. First time? Start with the keyboard basics: find the keys, the finger numbers and the falling notes.`)
    : "Do the 5 setup steps one time. Then the app knows your keyboard.";
  $("start-btn").textContent = calibrated ? "Start today's practice" : "Start the setup";
  $("home-progress").classList.toggle("hidden", !calibrated);
  if (habit) {
    const n = habit.streak.days;
    $("hp-streak").textContent = `${n} day${n === 1 ? "" : "s"}`;
    $("hp-today").textContent = `${Math.floor(habit.today_minutes)} of ${habit.goal_minutes} min`;
  }
  if (course) $("hp-level").textContent = course.all_done ? "All levels done" : `Level ${course.level}`;

  // Keyboard card
  $("home-kb-pill").className = `pill ${status.connected ? "pill-ok" : "pill-bad"}`;
  $("home-kb-pill-text").textContent = status.connected ? "Connected" : "Not connected";
  $("home-kb-text").textContent = status.connected
    ? `The app uses this device: ${status.port}.`
    : "Connect the keyboard to the Mac. Then go to Setup and click \"Find my keyboard\".";
  // Setup not done: "Open Setup". Else: free play (names of the keys that you press).
  const ready = status.connected && calibrated;
  $("home-kb-btn").textContent = ready ? "Open Free play" : "Open Setup";
  $("home-live-text").textContent = status.connected
    ? "Press a key on your keyboard. It lights up here."
    : "When the keyboard is connected, the keys that you press light up here.";

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
    $("tile-touch-hint").textContent = "Setup step 4 checks it.";
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
  if (status.calibration && status.calibration.calibrated) show("today");
  else { show("setup"); goStep("connect"); }
});
$("home-kb-btn").addEventListener("click", () => {
  if (status.connected && status.calibration && status.calibration.calibrated) show("play");
  else { show("setup"); goStep("connect"); }
});
// Home: 2 octaves around middle C that light up live (C below middle C to the C above).
const homeKb = new Keyboard($("home-keyboard"), { low: 48, high: 72, compact: true });

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
  $("held-names").textContent = pitches.length ? pitches.map(shortKeyName).join("  ") : "—";
}

link.on("note_on", (e) => {
  down.add(e.pitch);
  sounding.delete(e.pitch);
  kb.setHeld(e.pitch, false);
  kb.setDown(e.pitch, true);
  miniKb.setDown(e.pitch, true);
  homeKb.setDown(e.pitch, true);
  if ($("opt-mac-sound").checked) piano.noteOn(e.pitch, e.vel);
});

link.on("note_off", (e) => {
  down.delete(e.pitch);
  kb.setDown(e.pitch, false);
  miniKb.setDown(e.pitch, false);
  homeKb.setDown(e.pitch, false);
  if (pedal && e.reason !== "disconnect") {
    sounding.add(e.pitch);
    kb.setHeld(e.pitch, true);
  } else if ($("opt-mac-sound").checked) {
    piano.noteOff(e.pitch);
  }
});

link.on("cc", (e) => {
  if (e.control !== 64) return;
  // The first real foot switch down (value 64 or more) shows it: some keyboards send one CC 64 = 0
  // with no foot switch.
  if (e.reason !== "disconnect" && e.value >= 64) $("pedal-box").classList.remove("hidden");
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
  // A name with a black key (C#, Bb) waits for the sharp/flat words (Level 4). The sound words stay.
  const blackName = e.chord && !WORDS.sharpFlat && /[#b]/.test(e.chord.root + e.chord.bass);
  if (e.chord) {
    $("chord-name").textContent = blackName ? "—" : e.chord.name;
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
    if (li.dataset.step === s) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    li.classList.toggle("done", passed.has(li.dataset.step) && li.dataset.step !== s);
  }
  $("step-back").disabled = s === STEPS[0];
  $("step-next").textContent = s === STEPS.at(-1) ? "Finish" : "Next";
  renderNextButton();
}
for (const li of document.querySelectorAll("#stepper li")) {
  // Keyboard users: Tab to a step, then Enter or Space.
  li.tabIndex = 0;
  li.setAttribute("role", "button");
  li.addEventListener("click", () => goStep(li.dataset.step));
  li.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); goStep(li.dataset.step); }
  });
}
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

// ------------------------------------------------------------------ settings: tap with the click
// Latency calibration (PLAN 4 Timing, riyaz/tapcheck.py). The server gives the click times (server
// clock); the page plays them on the Mac (clock offset from the ping/pong sync). The user presses
// any key with each click; the server finds the median delay and Play along takes it away.

const tap = { running: false, timers: [], n: 0 };

function tapDots(count, now = -1, tapped = 0) {
  const box = $("tap-dots");
  box.innerHTML = "";
  for (let i = 0; i < count; i++) {
    const d = document.createElement("span");
    d.className = "tap-dot" + (i < tapped ? " tapped" : "") + (i === now ? " now" : "");
    box.appendChild(d);
  }
}

function tapStatus(text, tone = "") {
  const el = $("tap-status");
  el.textContent = text;
  el.className = "tap-status" + (tone ? ` ${tone}` : "");
}

function renderTapNow(st) {
  $("tap-now").textContent = st && st.done ? `Correction now: ${Math.round(st.offset_ms)} ms.` : "No correction yet.";
  $("tap-reset").disabled = !(st && st.done);
}

// "Forget the foot switch" (Settings): the foot switch parts hide again until the next foot switch down.
function renderPedalSetting(seen) {
  $("pedal-forget").disabled = !seen;
  $("pedal-now").textContent = seen ? "The app found a foot switch." : "The app did not find a foot switch.";
}
async function loadPedalSetting() {
  const st = await api("/api/pedal").catch(() => null);
  if (st) renderPedalSetting(st.seen);
}
$("pedal-forget").addEventListener("click", async () => {
  const st = await api("/api/pedal/forget", {}).catch(() => null);
  if (st) renderPedalSetting(st.seen);
});
link.on("pedal", (e) => {
  if (!e.seen) { $("pedal-box").classList.add("hidden"); $("pr-pedal").classList.add("hidden"); }
  if (current === "settings") renderPedalSetting(e.seen);
});

async function loadTapSetting() {
  const st = await api("/api/settings/latency").catch(() => null);
  renderTapNow(st);
  if (!tap.running) tapDots(8);
}

async function tapStart() {
  if (tap.running) return;
  await piano.start().catch(() => false); // sound starts in this click
  if (!piano.running) return tapStatus("The app cannot play the click. Turn on the Mac sound and try again.", "bad");
  if (link.serverNow() === null) return tapStatus("The app is not ready. Wait a moment and try again.", "bad");
  let plan;
  try {
    plan = await api("/api/settings/latency/start", {});
  } catch (e) {
    return tapStatus(e.message, "bad");
  }
  tap.running = true;
  tap.n = 0;
  $("tap-start").disabled = true;
  tapDots(plan.clicks.length);
  tapStatus("Listen. Press any key with each click.");
  const sNow = link.serverNow();
  const aNow = piano.audioNow();
  plan.clicks.forEach((t, i) => {
    piano.clickAt(aNow + (t - sNow), i === 0);
    tap.timers.push(setTimeout(() => tapDots(plan.clicks.length, i, tap.n), Math.max(0, (t - sNow) * 1000)));
  });
  tap.timers.push(setTimeout(tapFinish, Math.max(0, (plan.end - sNow) * 1000 + 300)));
  tap.count = plan.clicks.length;
}

async function tapFinish() {
  tap.timers.forEach(clearTimeout);
  tap.timers = [];
  const r = await api("/api/settings/latency/finish", {}).catch((e) => ({ ok: false, text: e.message }));
  tap.running = false;
  $("tap-start").disabled = false;
  $("tap-start").textContent = "Do the check again";
  tapDots(tap.count || 8, -1, Math.min(tap.n, tap.count || 8));
  tapStatus(r.text || "", r.ok ? "good" : "bad");
  renderTapNow(r);
}

link.on("tapcheck_tap", (e) => {
  if (!tap.running) return;
  tap.n = e.n;
  const now = [...document.querySelectorAll("#tap-dots .tap-dot")].findIndex((d) => d.classList.contains("now"));
  tapDots(tap.count || 8, now, Math.min(tap.n, tap.count || 8));
});

window.riyaz.tap = { state: tap, dots: tapDots, status: tapStatus, now: renderTapNow, load: loadTapSetting }; // checks
$("tap-start").addEventListener("click", tapStart);
$("tap-reset").addEventListener("click", async () => {
  const st = await api("/api/settings/latency/reset", {}).catch(() => null);
  renderTapNow(st);
  tapStatus("The app removed the correction. Play along now uses the key times as they come.");
});

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
terms.onChange(() => { practice.refreshWords(); kb.refreshLabels(); });
terms.load();
loadCourse();
refreshHabit();
api("/api/state").then((s) => {
  renderStatus(s);
  // Home shows the next action. If the setup is not done, the Start card points to it.
  show("home");
}).catch(() => show("home"));
