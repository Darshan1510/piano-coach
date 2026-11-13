# Decisions

Changes from `PLAN.md`, with the reason. Newest at the end of each section.

## Approved changes from RESEARCH.md (all 16 approved by the user, 2026-11-13)

1. **Python 3.12**, not 3.11–3.13. `python-rtmidi` 1.5.8 has no cp313 wheel and its source build fails on macOS arm64 with 3.13. `.python-version` = 3.12, `requires-python = ">=3.12,<3.13"`.
2. **`websockets`** is a dependency (Uvicorn has no WebSocket support without it). `Riyaz.spec` collects it.
3. **PyInstaller**: collect `mido`, `rtmidi`, `websockets` (plus uvicorn, fastapi, starlette, webview); hidden import `mido.backends.rtmidi`; copy `mido` metadata. The Makefile calls `Riyaz.spec`, so the flags live in one place (DocKit passes flags in the Makefile; its `.spec` is not used).
4. **MIDI filter** (`riyaz/midi_io.py`): only `note_on`, `note_off`, CC 64 pass. Clock, start/stop, sysex, program change, other CCs, active sensing are dropped. After calibration only the calibrated channel passes. `note_on` velocity 0 = `note_off`. If the app sets Local Off (CC 122), it sends Local On at exit, and at the next connect if the app stopped without that (flag `midi.local_off_pending`). Phase 1 never sets Local Off.
5. **Setup text** adds: PC mode OFF (hold DEMO), no style or song during practice, DUAL and SPLIT off, TOUCH on, TRANSPOSE 0 / OCTAVE 0.
6. **Hot-plug**: see "Phase 1 findings" below.
7. **Tone.js 15.1.22** vendored as `static/vendor/tone.min.js` (the `build/Tone.js` file is already minified). **Salamander MP3** samples A1–A7, C1–C8, D#1–D#7, F#1–F#7 (29 files, 1.9 MB) in `static/samples/salamander/`. `await Tone.start()` runs in the first click. `make vendor` downloads them with curl. No Node.js.
8. **Port 8020** with `PORT` env and a free-port fallback.
9.–11. Phase 5 audio items: not done yet (Phase 5).
12. **Song list** (Phase 2+ content; user decision 2026-11-13):
    - Remove **Saare Jahan Se Achha**. The familiar melody is by Ravi Shankar (1945), protected in India until 2073.
    - **Vande Mataram stays, but use ONLY Tagore's 1896 tune** (Tagore d. 1941, public domain in India since 2002). Do not use the Hemanta Mukherjee film tune (1952) or other later tunes.
    - Keep **Raghupati Raghav Raja Ram** (medium confidence): traditional words (Lakshmanacharya, "Sri Nama Ramayanam"; Gandhi's edit), familiar tune credited to V. D. Paluskar (d. 1931). Do not copy film versions (1954 "Jagriti", 1998 "Kuch Kuch Hota Hai").
    - Level 4 needs one more song for Saare Jahan Se Achha (proposal: "Oh! Susanna", Foster 1848). Decide in Phase 5.
13. Phase 3 MIDI fixtures: Mutopia pieces marked Public Domain, or CC BY with credit. Not done yet.
14. **App Nap**: `main.py` calls `NSProcessInfo.beginActivityWithOptions_reason_` (user-initiated, latency-critical, idle system sleep allowed) for the life of the app. Phase 1 has no "session", so the activity covers the whole run. "Pause when the window is hidden" comes with the song player (Phase 2).
15. **Tests** set `RIYAZ_DATA_DIR` to a temp folder. CoreMIDI tests are only in `tests/test_midi_virtual.py` and skip if virtual ports do not work.
16. pianoplayer (MIT) is allowed as a dev-only comparison (Phase 3).

## Project-local environment (user rule: nothing global)

- `uv` settings in `pyproject.toml`: `cache-dir = "./.cache/uv"`, `python-downloads = "manual"`, `python-preference = "managed"`.
- `UV_PYTHON_INSTALL_DIR` has **no** `pyproject.toml` setting (uv 0.9.13 rejects `python-install-dir`), so the Makefile and `env.sh` export it, with `UV_PYTHON_PREFERENCE=only-managed` and `PYINSTALLER_CONFIG_DIR=./.cache/pyinstaller`.
- `python-preference` in `pyproject.toml` is `managed`, not `only-managed`. With `only-managed` and no exported install dir, a plain `uv run main.py` (acceptance check 1) fails: uv does not count the `.venv` interpreter as managed. With `managed` + `python-downloads = "manual"`, a plain `uv run` reuses `.venv` and can never download Python to a global folder.
- Folder names: `.cache/uv`, `.cache/python` (user's names), not `.uv-cache`/`.uv-python` from RESEARCH.md.
- Test client: Starlette 1.10 asks for `httpx2`. The dev group uses the well-known `httpx` (Starlette falls back to it; a deprecation warning is filtered in pytest config).

## Yamaha YPT-320 facts (PLAN Section 2 asks to check these)

Source: PSR-E323/YPT-320 Owner's Manual and Data List (MIDI implementation chart), Yamaha website (checked in RESEARCH.md, 2026-11-13).

- 61 keys, C1–C6 (Yamaha naming), touch response. MIDI 36–96, middle C = 60 ("C3" in Yamaha naming). The plan is correct. The app still calibrates.
- Connectors: MIDI IN/OUT (5-pin DIN), SUSTAIN, PHONES/OUTPUT, DC IN 12V. **No USB.** The manual names the UX16 or a similar USB-MIDI interface.
- Note off is sent as **Note On velocity 0**. Velocity 1–127.
- **CC 64 (sustain) is sent.** Do not press the footswitch at power-on (polarity check).
- Also sent: program change, CC 0/32/7/10/72/91/93, sysex, MIDI clock + start/stop (when a style plays), active sensing. Channels 1–16.
- PC mode (hold DEMO): OFF (default) = Local On, song/style/keyboard out on. PC2 = Local Off. PC1 = no keyboard notes out (do not use). In PC mode OFF, style accompaniment notes also go out on MIDI → the channel filter.
- Local control: function setting, and CC 122 is received.
- TRANSPOSE −12..+12 and OCTAVE settings change the sent notes → calibration.
- TOUCH can be off → all velocities equal → setup step 4 detects it.
- Polyphony 32. C1 + C#1 together = a remote-control shortcut (avoid in songs).
- **DUAL and SPLIT** voices can send notes on other channels. With the channel filter, SPLIT left-hand notes may be dropped. Setup text says "Turn off DUAL and SPLIT." Check with the real keyboard (open issue).

## Phase 1 findings and choices

- **CoreMIDI hot-plug (RESEARCH change 6) — found and fixed.** The first version polled from a background thread, after the first port scan ran on another thread. A keyboard (fake port in another process) that appeared later was **never** seen; "Find my keyboard" worked by chance (same worker thread). A probe script showed the rule: CoreMIDI updates the port list only for the thread that made the process's first CoreMIDI client. A fresh `MidiIn()` per poll (mido does this) is not enough. **Fix:** one MIDI thread owns all CoreMIDI calls (first client, list, open, close, send); other threads hand work to it. A CFRunLoop on that thread is not needed (tested). Test: `test_hotplug_cross_process_real_app` (real `main.py --server` + fake player in another process; plug-in seen after ~2 s).
- **Auto-pick**: remembered port first; else the only input port, but ports named `IAC Driver…` do not count. If there are 2 or more, the user selects in the setup screen.
- **Output port** for the test note = the output with the same name as the input (USB-MIDI cables do this).
- **Chord names** come from the backend (`theory.py`) in a `keys` event after each key event, so the logic is in Python and tested. A name needs 3 or more different keys. Symbols use flats for Bb, Eb, Ab, Db roots and sharps for the others.
- **Free play words (PLAN 7.4).** Free play shows note letters and chord symbols, but no locked words: "You press", "Name of these keys together", "happy sound" / "sad sound" (not "chord", "major", "minor", "sharp"). Black keys show `C#` etc. only while pressed. White keys show letters (option to hide). No octave numbers on screen (60 = C4 in code; Yamaha calls it C3).
- **User has no sustain pedal; pedal UI hidden until CC64 seen; pedal lessons (Level 9) must be optional/skippable.** The backend CC 64 handling and the sustain sound logic stay (Phase 6).
- **Mac sound for the user's own keys** is off by default (the user hears the keyboard). Clicks on the screen keyboard always play the Mac sound. Option: "Also play my keys on the Mac speaker".
- **Delay measurement**: the UI keeps a clock offset (ping/pong, median of 5, again every 30 s), measures callback→WebSocket receipt and callback→next animation frame, and sends reports to `/api/debug/latency`. The About screen shows the median for the last 50 keys (for the real-keyboard check).
- **main.py** waits for the server before it opens the window, and stops the server after the window closes, so that shutdown code runs (ports close, Local On).
- **Icon**: none yet (`Riyaz.spec` `icon=None`). Bundle id `local.riyaz.app`.

## Phase 1 UI redesign (user request 2026-11-13: "a bit like an enterprise app, easy and fun")

- **App shell**: left sidebar + top bar. The sidebar items come from one list, `NAV` in `static/app.js` (with `ICONS`). A later phase adds one entry there and one `<section id="screen-ID" class="screen">` in `index.html`. Only screens that work are in the list (Home, Free play, Setup, Settings, About). No "coming soon" screens. Below 1240 px window width, the sidebar shows only icons.
- **Top bar**: page title, streak ("0 days") and "0 min today" slots, sound button, theme button, keyboard status. Phase 1 records no practice, so 0 is the true value. Phase 3 (daily session, streak) fills `#streak-text` and `#minutes-text`.
- **Home** is the first screen (before: Setup if not calibrated). Its Start card points to Setup when the setup is not done, else to Free play. A dot on the "Setup" sidebar item shows that the setup is not done.
- **Design tokens**: all colors, spacing, radius, font sizes, shadows and motion times are CSS variables in `:root` (`static/style.css`). Dark theme is the default. `[data-theme="light"]` changes only the color tokens. The choice is kept in `localStorage` key `riyaz.theme` (all access in try/catch). A small inline script in `<head>` sets the theme before the first paint.
- **App color = purple** (buttons, nav, live keys). Blue and green are kept for the hands: right hand `--hand-right` (Okabe-Ito blue), left hand `--hand-left` (Okabe-Ito bluish green), safe for color-blind people. Phase 2 uses them. The middle C step text says "The purple key below shows the place."
- **Motion**: UI transitions are 90–160 ms. A pressed key lights at once (no transition) and glows; the release fades in 160 ms. A setup step that passes shows a check mark pop and a short CSS confetti burst (850 ms). `prefers-reduced-motion: reduce` turns off all animation and the confetti.
- **One primary button per screen**: in Setup, the step's own button is primary until the step passes; then "Next" becomes primary.
- **"Do the setup again"** moved from About to Settings (with a note that it removes the results).
- **Window**: `main.py` 1280 × 820, minimum 1100 × 680 (before 1180 × 760, minimum 900 × 600), so that the 61 keys are at least about 26 px wide.
- System font stack only. No network fonts, no CDN, no build step.

## Phase 1 review fixes (2026-11-13)

- **Host and Origin checks** (`riyaz/server.py`). `TrustedHostMiddleware` allows only `127.0.0.1` and `localhost` (else HTTP 400; stops DNS rebinding). The WebSocket and all POST/PUT/PATCH/DELETE requests need no `Origin` header (Python tools, tests) or the app's own origin `http://127.0.0.1:<port>` / `http://localhost:<port>` (port from the Host header). Else: WebSocket close 1008 (HTTP 403), POST 403. GET has no Origin check (it changes nothing). The WebSocket message protocol is the same.
- **Bad WebSocket input is ignored**: not JSON, not an object, or a bad `latency_report` (a bad report adds no values). Each client queue holds 512 events; when full, the oldest event is dropped.
- **`RIYAZ_PORT_FILTER=prefix`**: `MidiService` (and so the app) sees only MIDI ports whose name starts with the prefix. The CoreMIDI tests set it to their virtual port and add a stand-in "USB MIDI Interface" port, so they pass when the real keyboard is plugged in.
- **Channel filter and held keys**: the note off of a key in `held` always passes, on any channel (before, a key pressed before calibration, or in the "test" step, on another channel stayed lit). The "test" step accepts only the calibrated channel once one is known. The middle C step still listens on all channels.
- Disconnect sustain-off event: `ch` is 1–16 (calibrated channel, else 1), like the other events.
- **Test note** (`play_test_note`): daemon timer; `stop()` cancels it and sends its note off at once; after `stop()` no send opens the output again.
- **main.py**: the bound socket goes to uvicorn (no check-then-bind race). The window waits up to 20 s for the server; if it does not start, the app logs an error and exits (no dead window). After the window closes, it waits up to 25 s for shutdown (`midi.stop()` can take about 15 s).
- **install.sh**: `xattr -dr com.apple.quarantine` (not `xattr -cr`). A running Riyaz is asked to quit (osascript, bundle id) before the old app is removed; if it still runs after 10 s, the installer stops.
- **Phase 6 release flow (to do then, not built now)**: publish a SHA-256 file with each release zip (`shasum -a 256`), and make `install.sh` download it and check the zip before unpacking.
- **Tests** keep their data in `.cache/test-data/run-<pid>/` (session data dir and pytest `tmp_path`), not `/var/folders`. The folder is removed at the end of the run. One folder per process, so 2 runs at the same time do not clash. (Replaces item 15 "temp folder".)
- **PyInstaller** is in the `dev` dependency group (build only; `uv sync` installs the dev group by default). `Riyaz.spec` sets `PYINSTALLER_CONFIG_DIR` to `.cache/pyinstaller` (and PyInstaller's `CONF["cachedir"]`, which PyInstaller computes before it reads the spec) when the variable is not set, so a direct `uv run pyinstaller Riyaz.spec` stays local. Do not use `--clean` without the variable: PyInstaller cleans its cache dir before it runs the spec.
- **Latency test**: one retry if the first 200-note run is slow (busy machine). The acceptance number stays the UI paint delay in PROGRESS.md.

## Phase 2 (2026-11-13): songs, falling notes, watch and wait mode

- **Song files** in `data/songs/*.json` (PLAN 5.1 format; `start`/`dur` in beats). Loader and checks: `riyaz/songs.py`. A bad file is skipped and logged. Extra fields: `order` (place in the list), `credit`, and the computed `end` (beats). `Riyaz.spec` bundles `data/songs`. `RIYAZ_EXTRA_SONG_DIR` loads more songs from a folder (test songs only, for example the generated 200-note song from `tools/make_test_song.py`).
- **Format extension: `hand_positions[].keys`** (optional, 5 pitches, thumb first). Without it, the 5 fingers sit on 5 white keys next to each other (up from the thumb for R, down for L). Frère Jacques needs a spread hand (C E F G A) for "G A G F E C". A test checks that each note's finger is on the note's key in the hand position at that time.
- **The 6 songs** (Level 1: Mary Had a Little Lamb, Ode to Joy, Twinkle Twinkle; Level 2: Au Clair de la Lune, Frère Jacques, London Bridge). All traditional or Beethoven (1824), public domain; the easy arrangements and fingering are new (written for Riyaz). White keys only, one key at a time for each hand, 90 bpm, 4/4.
  - Mary uses the real melody with G (4 keys: C D E G), not the PLAN "3 keys" version. All 4 keys are in the C position.
  - Ode to Joy: the first half only (A A', 32 beats). The B part needs the low G (a hand move), which is not a Level 1 skill.
  - Twinkle has 6 different keys (C to A): the thumb moves C → D → C (arrow and "Move your right hand to D" one beat early). This is the Level 1 skill "small jumps".
  - Au Clair de la Lune is in F (all white keys: C D E F G A). Thumb on D, then on C for Part 3.
  - Frère Jacques: C position, then a spread hand, then "Move your right hand to G" (G below middle C).
  - London Bridge: thumb on D, then on C for the end.
  - Level 2 songs have a simple left-hand part (one long key every 4 counts, thumb on the C below middle C). The app plays it by default ("The app plays the left hand"). The user can also select Left or Both. Level 1 songs have the right hand only.
- **Song clock** (`riyaz/practice.py`): `beat = anchor_beat + (t - anchor_t) * rate`, `t` = `clock.now()` (same clock as the MIDI stamps). Each change sends a `practice` event with the anchor. The UI uses the Phase 1 clock offset (ping/pong, median of 5) and clamps at `hold_beat` in wait mode, so it stops at the line without waiting for a message. A thread checks the clock every 5 ms (wait stop reached, end, loop, keyboard output).
- **Wait mode** (`riyaz/matcher.py`): as PLAN 6.4. Extra rules: only presses after a stop became current count (a repeated key must be pressed again); a correct key up to 0.5 beat before its note reaches the line counts (`WAIT_EARLY_BEATS`); a correct key earlier than that is ignored (not wrong); keys during the count-in are ignored. A wrong key = any key that is not in the expected set: red key, red mark at the line, `practice_wrong` event, logged in `matcher.errors`, the song does not go on.
- **WebSocket protocol: extended only.** New event types `practice`, `practice_hit`, `practice_wrong`, `practice_end`. Phase 1 events and messages did not change. Practice control uses REST (`/api/practice/start|pause|resume|stop|speed`, `GET /api/practice`, `GET /api/songs[/id]`), so the Origin check (POST) protects it.
- **Watch mode sound**: Mac (Tone.js, notes scheduled 150 ms ahead on the AudioContext clock, without the Tone.js look-ahead) or the keyboard speaker (backend sends the notes on MIDI OUT with the calibration offset taken back; only when the setup found an output port). MIDI sends happen after the practice lock is released (no deadlock with the MIDI thread).
- **The click and count-in**: Mac only (Tone.js Synth). Count-in = 4 clicks (time signature) before the song or the repeated part. Words: "The click", "4 clicks before the start", "Speed" (PLAN 7.4).
- **Loop** = "Repeat Part N" (the song's `sections`, PLAN 7.4 Rule 1): the part repeats with no count-in; a colored band shows the part on the falling notes. No automatic speed step (that is Phase 4 adapt).
- **Option changes** (how, hands, part, count-in, other hand, keyboard sound) stop the song; speed and the click change live.
- **Pause when hidden**: the page pauses on `visibilitychange` (hidden) and `pagehide`, and when no animation frame came for 1 s while the song runs (window behind other windows). It sends the last drawn beat, so the song goes back to what the user saw. `main.py` also pauses on the pywebview `minimized` event. The user clicks "Continue".
- **No bar lines** (PLAN 7.4 Rule 5): the renderer has `showBarLines`, false in Phase 2 (all songs Level 1–2, no user level yet).
- **Renderer**: Canvas 2D (no PixiJS): a lane background drawn once into an off-screen canvas, binary search for the first visible note, only visible notes drawn; hand outline on a second canvas over the keyboard (`static/js/hands.js`). Key places come from one function `keyLayout()` in `keyboard.js` (keyboard and notes use the same numbers).
- **Home**: the Start card points to Songs after the setup. The keyboard card shows a live 2-octave keyboard (real key presses), so the card has no empty space.

## Phase 2 review fixes (2026-11-13)

- **Mac sound schedule starts at the anchor.** After a new run, a loop pass, a jump back or a pause, `practice.js` schedules notes and clicks from `min(beat, anchor_beat)` (not from "now"), but not more than 0.25 s back (`LATE_MAX_S`). A late note plays at once (`when = now + max(0, …)`). Before, the first note and the first click of a part were lost on each loop pass and at a start without count-in.
- **Echo guard** (`EchoGuard` in `riyaz/practice.py`, `ECHO_WINDOW_S = 0.05` in `config.py`). Practice records (raw pitch, send time) of each song note that it sends to the keyboard. `MidiService.echo_filter` drops a note_on with the same raw pitch within 50 ms of a send (one echo for each send), and the note_off of that key. A dropped echo does not light a key, does not go into `held` and does not reach the matcher. The filter is in `MidiService.handle_message` (not in the server sink), so the `keys` event (names) does not show the echo either.
- **Finger-number contrast (WCAG AA ≥ 4.5:1).** Tokens `--on-hand-right`, `--on-hand-left`, `--dot-edge` replace `--on-hand`. Dark: dark text on both hand colors (8.2:1, 7.6:1). Light: white on blue (5.2:1), dark on green (5.5:1). A faded note (other hand, or done) has its number in `--text` at full strength (6.4–9.5:1). Finger dots are solid: next finger = hand color + dark outline; other fingers = white dot, hand-color ring, dark text.
- **Practice keyboard layout**: the key letters sit just below the black keys (`top: 64%`); the finger dots are below the letters, the hand at the bottom. The key to press: the soft hand color is drawn over the white key color (before, the half-transparent color showed the dark page: "dark blue" key in the dark theme). A letter on a key that the app plays uses the `--on-hand-*` color.
- **Blocking practice calls** (start, pause, resume, stop, speed) run in `asyncio.to_thread` (they can send MIDI).
- **Events `practice_hit` and `practice_wrong` have `song_id` and `run`** (fields added; protocol stays compatible). The UI ignores an event for another song or run (and accepts events without the fields).
- **UI order**: a `song_id: null` state with an older `seq` is ignored. An option change waits for its stop before a new start.
- **User texts**: PracticeError and HTTP error texts are full ASD-STE100 sentences. The 409 text names the real switch: `Turn off "Play the song on the keyboard speaker".` A bad `hands` (or `mode`, `output`, `section`) type gives 400, not 500. The UI shows a FastAPI 422 list as text. Pause reason "left" has its own text ("…because you went to a different page.").
- **Sharp/flat words (PLAN 7.4, Level 4)**: one flag, `WORDS.sharpFlat` in `static/js/keyboard.js` (false now). While false: black keys have no letter label, text says "the black key right of C" (`keyName`), the free play list says "black key" (`shortKeyName`), and a free play name with a black-key root or bass (C#, Bb) shows "—" (the happy/sad sound words stay). The course sets the flag at Level 4 and calls `Keyboard.refreshLabels()`. `noteName()` stays for code.
- "Setup step 4 measures it." → "Setup step 4 checks it." The count-in text comes from the song's time signature ("4 clicks before the start").
- **Locked-word test** (`tests/test_server.py`): scans the visible HTML text and `title`/`aria-label` values, string literals in `practice.js`, `songs.js`, `hands.js`, `app.js`, song titles and part names, and all `PracticeError`/`HTTPException` texts in `riyaz/` (also: capital letter, full stop). Words: sharp, flat, major, minor, scale, interval, progression, bar, measure, beat, tempo, chord, rest (and plurals), word boundary, any case. Allowed: a string with no space that is all lower case or has `-`, `_`, `/`, `.`, `#` (ids, classes, event types, keys). `test_melodies_start_correctly` also checks the rhythm of the first phrase.
- **Accessibility**: setup stepper items are focusable (`tabindex=0`, `role=button`, Enter/Space, `aria-current=step`); arrow keys move the choice in each `role="radio"` group (`radioKeys()`; only the checked button is in the Tab order); the end card's button gets the focus; the falling-notes canvas has `role="img"`.
- **Practice options are kept** (speed, the click, the count-in) in the settings table, key `practice.options` (one user). `GET`/`POST /api/settings/practice`; speed is clamped, non-bool values are ignored. Hands, part, mode and keyboard sound are not kept (they depend on the song).
