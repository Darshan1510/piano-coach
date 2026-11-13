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
