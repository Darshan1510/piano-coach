# Progress

## Status

- **Stage:** Phase 1 review fixes (done, not committed). Before: Phase 1 UI redesign; Phase 1 built and verified (Stage 3 + 4). Not committed yet (`git init` done, no remote). The user reviews, then commits.
- **Next:** manual checks below, then Phase 2.

## Phase 1 review fixes (2026-11-13)

Details and reasons: `DECISIONS.md` "Phase 1 review fixes".

- Server: Host check (400), Origin check on WebSocket (close 1008 / 403) and POST (403); bad WebSocket messages ignored; client queue max 512, oldest dropped.
- MIDI: `RIYAZ_PORT_FILTER`; held-key note off passes the channel filter; "test" step uses the known channel; disconnect sustain-off `ch` 1–16; test-note timer is daemon and stop() sends its note off.
- `main.py`: bound socket to uvicorn; startup error instead of a dead window; longer shutdown wait.
- `install.sh`: `xattr -dr com.apple.quarantine`; quit a running Riyaz first. Checksums: Phase 6 note in DECISIONS.md.
- Tests: data in `.cache/test-data/run-<pid>/`, removed after the run. CoreMIDI tests use the port filter (+ a stand-in "USB MIDI Interface" port). Latency test: one retry.
- PyInstaller in the dev group; `Riyaz.spec` keeps its cache local without the Makefile.

Results: `uv run pytest` **55 passed** (21 s). Checks with a real server (`main.py --server` and frozen `Riyaz.app --server`, preferred port busy -> free port used): no Origin OK, own Origin OK, foreign Origin WebSocket 403, foreign Origin POST 403, bad Host 400; 200/200 fake notes, right pitches (frozen: median 0.47 / p95 1.02 ms). `make build-mac` OK (42 MB). A direct `uv run pyinstaller Riyaz.spec` without `PYINSTALLER_CONFIG_DIR` used `.cache/pyinstaller` (global folder not changed). Frozen app WINDOW: the WKWebView page got 100/100 notes (receipt median 1.17 / p95 1.72 ms; frame median 9.39 / p95 16.95 ms, window maybe not in front); no requests blocked.

## Phase 1 UI redesign (2026-11-13)

User request: "make it a bit like enterprise app so that it is easy and fun to use". Only `static/` and the window size in `main.py` changed. No backend or WebSocket protocol change. Design notes: `DECISIONS.md` "Phase 1 UI redesign".

- App shell: sidebar (Home, Free play, Setup, Settings, About; one `NAV` list in `static/app.js`) and top bar (page title, "0 days" streak, "0 min today", sound, theme, keyboard status).
- Home: Start card (Setup or Free play), keyboard card, card with the setup results in plain words (middle C, note correction, channel, soft and loud).
- Design tokens in `static/style.css`; dark theme default, light theme (top bar button or Settings), kept in `localStorage`.
- Key glow, short transitions, check mark pop and CSS confetti when a setup step passes; all off with reduced motion.
- Setup: numbered stepper with check marks; one primary button at a time; "Find my keyboard" above the settings box; cable diagram labels no longer under the cables.
- Window 1280 × 820, minimum 1100 × 680.

Checks (pywebview window driven by a scratch script + fake player, server on port 8123 with a temp data folder):
- No JS errors. 5 sidebar items. Fake player: keys light (C E G → 3 keys down), "C" + "happy sound". Pedal box hidden until the first CC 64, then shown. Theme kept in `localStorage`.
- No horizontal scroll at 1280 and 1100 px. Keyboard 974 px (1280) / 950 px (1100) wide.
- `tools/measure_latency.py`: send→WebSocket median 0.64 ms, p95 1.10 ms. UI next frame median 9.8 ms, p95 17.3 ms (window driven by the check script, with snapshots).
- Screenshots: WKWebView snapshots (`screencapture` has no screen-recording permission).

## Phase 1: done

- Skeleton: `main.py`, `Makefile`, `Riyaz.spec`, `install.sh`, `README.md` (with `make clean` / `make distclean`), `pyproject.toml`, `.python-version` (3.12), `.gitignore`, `env.sh`.
- `riyaz/config.py`, `riyaz/db.py` (settings only), `riyaz/clock.py`, `riyaz/theory.py` (note names, chord names), `riyaz/midi_io.py` (ports, auto-pick, remember choice, hot-plug every 2 s, vel-0 note off, CC 64, channel filter, calibration offset, touch range, output test note, Local On at exit), `riyaz/server.py` (FastAPI, REST, WebSocket).
- UI (`static/`): top bar with "Keyboard connected / not connected"; setup in 5 steps (cable diagram, PLAN 6.2 texts, find keyboard, 10-second test, middle C, soft/loud, keyboard sound test); free play with the 61-key keyboard, note names and chord names; About with credits and the delay check. Pedal readout hidden until the first CC 64.
- Mac sound: Tone.js 15.1.22 Sampler with local Salamander MP3s; sound starts on the first click.
- Tools: `tools/fake_player.py` (virtual port, `--shift`, `--noise`, `--chord`, vel-0 note off), `tools/measure_latency.py`.

## Test results (2026-11-13)

`uv run pytest`: **43 passed** (21 s).

| Acceptance check | Result | Evidence |
|---|---|---|
| 1. `uv run main.py` opens the app window | **Pass** (server + window), visual check **needs manual test** | Server on 8020 serves `/`, JS, Tone.js, samples. The WKWebView page loaded, opened the WebSocket and sent 200 delay reports. No traceback. |
| 2. Notes reach the UI in < 20 ms | **Pass** | Fake port send → WebSocket client: median **0.54 ms**, p95 **0.82 ms**, max 1.08 ms (pytest, n=200). Frozen app: median 1.02 / p95 1.30 ms. Inside the WKWebView (frozen app window): receipt median 1.15 / p95 1.68 ms; next frame median **1.41 / p95 2.09 ms**. |
| 3. Calibration stores the offset; +12 input shows correct notes | **Pass** | `test_calibration_with_shift_plus_12` (CoreMIDI) and `test_calibration_middle_c_with_plus_12_shift` (unit): offset −12 stored, C D E F G A B C come out as 60…72; restart keeps the offset. |
| 4. Tests pass | **Pass** | 43 passed. |
| Hot-plug | **Pass** (after a fix) | Real app process + fake port in another process: plug-in seen after 1.98–2.01 s, unplug seen, held keys released. |
| Frozen app gets fake-player notes | **Pass** | `make build-mac` 9 s, `Riyaz.app` 42 MB. 200/200 notes, correct pitches. |

Note on check 2: when the source-run window was behind other windows, WebKit slowed animation frames (frame delay median 108 ms, then no frames). This is macOS throttling of a hidden window, not the app. Check with the window in front (About screen → "Delay check").

## Open issues

- Visual check: done by WKWebView snapshots (UI redesign). The user still checks the real window.
- Real YPT-320 + cable not tested: channel, DUAL/SPLIT channels, CC 64 behavior, output test note, real hot-plug of a USB device.
- Sound (Tone.js in WKWebView) not heard by the builder.
- Hidden window throttles animation frames: Phase 2 must pause the song when the window is hidden (RESEARCH change 14).
- No app icon.
- Running the window wrote small WebKit caches outside the project: `~/Library/WebKit/local.riyaz.app`, `~/Library/Caches/local.riyaz.app`, `~/Library/WebKit/python3`, `~/Library/Caches/python3` (under 1 MB each). README "Clean" lists the remove command.
