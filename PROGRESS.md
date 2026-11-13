# Progress

## Status

- **Stage:** Phase 2 review fixes (2026-11-13). Phase 2 not committed (the user reviews, then commits). Before: Phase 1, commit 748bc96.
- **Next:** manual checks below (real keyboard, sound, window in front), then Phase 3.

## Phase 2 review fixes (2026-11-13)

Details and reasons: `DECISIONS.md` "Phase 2 review fixes".

- Mac sound: the first note and click of a part play (schedule from the anchor). Echo guard for song notes sent to the keyboard (50 ms). Practice REST calls in a thread. `practice_hit`/`practice_wrong` carry `song_id` and `run`. Old stop states ignored; option change waits for its stop.
- Finger numbers ≥ 4.5:1 in both themes (solid dots, `--on-hand-*` tokens). Dots no longer cover the key letters. Key to press no longer dark blue in the dark theme.
- Plain error sentences; 409 names the real switch; bad `hands` type = 400; 422 shown as text; own text for pause reason "left".
- No black-key letters before Level 4 (`WORDS.sharpFlat`). "Setup step 4 checks it." Count-in text from the time signature.
- Locked-word test covers HTML, 4 UI scripts, songs and backend texts; rhythm check for the first phrase.
- Accessibility: stepper by keyboard, arrow keys in radio groups, focus to the end card, canvas `role="img"`.
- Speed, the click and the count-in are kept in the settings database.

Results: `uv run pytest` **124 passed** (37 s; 6 new). `make build-mac` OK. Frozen `Riyaz.app --server`: 200/200 fake notes, no wrong pitch, send→WebSocket median 0.92 / p95 1.05 ms; foreign Origin POST 403; `/api/settings/practice` works.
WKWebView check (scratch driver, Mac sound stubbed to record the schedule): start without count-in → first note E and the first click (accent) at beat 0; count-in → 4 clicks then E; Mary "Repeat Part 1" at 150 %, 2 passes → the part's first note and first click on each pass (36 clicks for 32 beats). Pause on leaving the page → "…because you went to a different page." Arrow key Watch → Play. Focus on "Play again" at the end. No JS errors. Screenshots (dark + light, idle, wait, watch, end): the scratchpad folder (`phase2-fix/`).

## Phase 2 (2026-11-13): songs, falling notes, watch and wait mode

Details and reasons: `DECISIONS.md` "Phase 2".

- Songs: `data/songs/*.json` (6 songs, Levels 1–2, hand-written fingering and hand positions), loader and checks `riyaz/songs.py`, `GET /api/songs`, `GET /api/songs/{id}`. Bundled in `Riyaz.app`.
- Song clock and modes: `riyaz/practice.py` (backend is the source of truth; anchor + rate; count-in; loop a part; speed 25–150 %; pause/resume; keyboard-speaker output), `riyaz/matcher.py` (wait mode, PLAN 6.4). REST `/api/practice/*`; new WebSocket events `practice`, `practice_hit`, `practice_wrong`, `practice_end` (Phase 1 protocol unchanged).
- UI: sidebar item "Songs" (cards: level, hands, length, notes), Practice screen (`static/js/practice.js`): Watch / Play, Right / Left / Both, Part ("Repeat Part N"), Speed, "The click", "4 clicks before the start", "The app plays the left hand", "Play the song on the keyboard speaker" (only with a MIDI output). Falling notes `static/js/renderer.js` (Canvas 2D, finger numbers, hand colors, part band, count-in numbers, red mark for a wrong key, no bar lines), hand outline `static/js/hands.js` (5 finger dots, next finger bright, dashed new place + arrow + "Move your right hand to D." one beat early). Keys: app notes glow in the hand color, keys to press pulse, wrong = red, right = green. End card + confetti when a song is done in Play mode (no animation with reduced motion).
- Pause when hidden (Phase 1 open issue): `visibilitychange`, `pagehide`, 1 s without frames, pywebview `minimized`. A pause carries the `run` number, so an old pause cannot stop a new song (race found by the window check).
- Home: Start card → "Learn your first song" (after setup); keyboard card has a live 2-octave keyboard (no empty space).
- Tools: `tools/fake_player.py --song ID [--follow URL --wrong N]` (play a song in time, or follow wait mode in the app); `tools/make_test_song.py` (200-note test song); `RIYAZ_EXTRA_SONG_DIR`.

### Phase 2 acceptance (2026-11-13)

`uv run pytest`: **118 passed** (36 s; 63 new). `make build-mac`: OK, 42 MB.

| Check | Result | Evidence |
|---|---|---|
| 1. Renderer 60 fps, 200-note song | **Pass** | Real pywebview/WKWebView window (scratch driver), test song 200 notes, both hands, watch mode, 100 %, 1280 × 820, canvas 2028 × 516 px (DPR 2): **721 frames in 12 s, frame median 17 ms (16.7), p95 18 ms, max 18 ms, dropped 0 %**. Draw + hands + keys per frame: median 0 ms, p95 1 ms (WKWebView timer is 1 ms). Forced GPU flush per frame (getImageData): median 1 ms, p95 1–3 ms. Runs where the window was covered or the screen locked (page hidden) got no frames; they are not counted. |
| 2. Fake player completes wait mode, each built-in song | **Pass** | Backend, fake clock: `test_builtin_song_completes_in_wait_mode` (6 songs, all hands) and `test_every_builtin_song_completes_for_each_hand_choice` (matcher, R / L / both). End to end, real CoreMIDI, running app: `fake_player.py --song all --follow --wrong 2 --speed 1.5`: 6/6 PASS (Mary 26 stops, Ode 30, Twinkle 42, Au Clair 44, Frère Jacques 32, London Bridge 24; 14.7–29 s each). pytest `test_wait_mode_end_to_end_with_fake_player` (London Bridge). Frozen app: London Bridge PASS. |
| 3. Wrong keys turn red and do not advance | **Pass** | Backend: `test_wait_mode_holds_until_correct_key`, `test_wrong_key_logged_and_no_advance`, `test_practice_api_and_wait_events`. E2E: 12 wrong keys over 6 songs, 0 advanced the song (state checked after each). UI (WKWebView): wrong F → key has class `wrong` (red), stop 0 → 0, still waiting, beat 0.0, banner "Not this key. Press E with finger 3."; red goes away after release; right key E → green, stop 1. |
| Frozen app gets fake notes | **Pass** | `Riyaz.app --server`: 200/200 notes, no wrong pitch, median 0.78 / p95 1.21 ms. Origin/Host checks: foreign Origin WS 403, POST 403, bad Host 400. Songs in the bundle: 6. |
| No JS errors | **Pass** | `window.__errs` empty in all window runs. No horizontal scroll at 1280 px. |

Screenshots (WKWebView snapshots, dark + light): the scratchpad folder (`phase2/`).

### Open issues (Phase 2)

- Real YPT-320 not tested: wait mode with real keys, keyboard-speaker output (`output: keyboard`; does the YPT-320 send notes it receives back on MIDI OUT? If yes, the matcher sees them).
- Sound (song notes, the click) not heard by the builder. The click has no latency correction (IDEAS).
- The frame rate needs the window in front: WKWebView gives no frames to a covered window or a locked screen (the song pauses then, as planned).
- ~~Hand outline dots cover the key letters~~: fixed (review fixes).
- ~~Settings stay for the session only~~: speed, the click and the count-in are kept (review fixes).
- Echo guard: not tested with the real YPT-320 (does it echo? is 50 ms enough?).

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
- Hidden window throttles animation frames: done in Phase 2 (the song pauses when the window is hidden).
- No app icon.
- Running the window wrote small WebKit caches outside the project: `~/Library/WebKit/local.riyaz.app`, `~/Library/Caches/local.riyaz.app`, `~/Library/WebKit/python3`, `~/Library/Caches/python3` (under 1 MB each). README "Clean" lists the remove command.
