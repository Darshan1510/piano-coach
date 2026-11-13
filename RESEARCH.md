# Riyaz — Stage 2 research

Date: 2026-11-13. Sources were checked on PyPI, npm, GitHub, Hugging Face, Zenodo and Yamaha (links at the end).
Machine: MacBook Air M4 (Mac16,12), 16 GB RAM, macOS 27.0.1, uv 0.9.13, Xcode CLT present, gh present, no ffmpeg, no wget, no Ollama.

## Verdict

**Sound with changes.** The architecture works. Some steps fail as written:

- `python-rtmidi` has no Python 3.13 wheel. The source build fails on macOS arm64 with 3.13. Use Python **3.12**.
- `basic-pitch` 0.4.0 does not install on macOS with Python 3.12+ (it asks for `tensorflow-macos`, which has no cp312 wheel). Use a uv override and the bundled CoreML/ONNX model.
- Uvicorn without extras has no WebSocket support. Add `websockets`.
- 2 built-in songs are not clearly public domain (Saare Jahan Se Achha melody, Vande Mataram familiar melody).

See "Proposed changes" at the end.

---

## 1. Reference-app patterns (copy these)

Both apps (DocKit, passport-photo-tool) use the same pattern.

| Item | Pattern |
|---|---|
| Python | `.python-version` = `3.13`; `requires-python = ">=3.11,<3.14"`. **Riyaz must use 3.12** (Section 2). |
| Deps (pyproject) | `fastapi`, `uvicorn`, `pywebview>=6.1`, `pyinstaller>=6.19` (in main deps, not a dev group), `python-multipart`. No `[build-system]`; run with `uv run main.py`. |
| App object | `app = FastAPI()` at module level. |
| Port | `PORT = int(os.environ.get("PORT", "8010"))` (DocKit) / `"8000"` (passport). `URL = f"http://127.0.0.1:{PORT}"`. Fixed port, no free-port search. |
| Static | `get_static_path()`: `Path(sys._MEIPASS) / "static"` when frozen, else `Path(__file__).parent / "static"`. `app.mount("/static", StaticFiles(directory=get_static_path()), name="static")`. `@app.get("/", response_class=HTMLResponse)` returns `index.html`. |
| Temp files | DocKit: `Path(tempfile.gettempdir()) / "dockit" / uuid4().hex`, removed with `atexit` (the `.app` is read-only). |
| Server start | `def run_server(): uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")` |
| `__main__` | `--browser` flag: `threading.Timer(1.0, webbrowser.open, args=[URL]).start(); run_server(); sys.exit(0)`. Else: `threading.Thread(target=run_server, daemon=True).start()`, then `webview.create_window("DocKit", URL, width=1000, height=760, min_size=(640, 520), js_api=Api())`, then `webview.start()` (main thread). |
| JS bridge | `class Api` passed as `js_api` (used for native save dialogs: `webview.FileDialog.SAVE`). |
| Makefile | `PYI := uv run pyinstaller`; `ARCH := $(shell uname -m)`; `COLLECT := --collect-all uvicorn --collect-all fastapi --collect-all webview ...`. `build-mac`: `$(PYI) --noconfirm --onedir --windowed --add-data "static:static" $(COLLECT) --name "$(NAME)" --icon assets/app.icns $(ENTRY)`. `build-mac-ci`: `ditto -c -k --sequesterRsrc --keepParent "dist/$(NAME).app" "$(NAME)-macOS-$(ARCH).zip"`. `release-mac VERSION=v0.1.0`: `rm -rf build dist zip`, `make build-mac-ci`, `gh release create "$(VERSION)" "<zip>" --title "$(VERSION)" --generate-notes`. Also `build-windows`, `icon` (`uv run assets/make_icon.py`), `clean`. |
| `.spec` | DocKit.spec is the PyInstaller-generated file from the same flags (`collect_all(...)` per package, `BUNDLE(name='DocKit.app', icon='assets/app.icns', bundle_identifier=None)`, `upx=True`, `console=False`). The Makefile does not use it (it passes flags). Keep both in sync, or make the Makefile call the `.spec`. |
| install.sh | POSIX `sh`, `set -eu`. `REPO=`, `APP_NAME=`. Fails on non-Darwin and on x86_64 (arm64 only). Downloads `https://github.com/$REPO/releases/latest/download/$APP_NAME-macOS-arm64.zip` with `curl -fL`, unpacks with `ditto -x -k`, installs to `~/Downloads/$APP_NAME.app` (replaces old copy), runs `xattr -cr` (unsigned app, Gatekeeper), then `open`. |
| CI | `.github/workflows/build-release.yml`: on tag `v*`, matrix `macos-14` + `windows-latest`, `astral-sh/setup-uv@v5`, `uv python install`, `uv sync`, `make build-*-ci`, `softprops/action-gh-release@v2`. DocKit README: the release is done locally with `make release-mac`; the workflow is manual-only. |
| README | Sections: Install (curl one-liner), troubleshooting ("damaged" → `xattr -cr`), Run from source (`uv sync`, `uv run main.py`, `--browser`, `PORT=8123`), Build (`make build-mac`), Release (`make release-mac VERSION=...`), Rename repo notes. |

---

## 2. Technical soundness (question 1)

| Topic | Finding | Action |
|---|---|---|
| python-rtmidi wheels | Latest is **1.5.8 (2023-11-20)**. macOS arm64 wheels: cp38–cp312 only. **No cp313/cp314.** Issue #217: sdist build on macOS arm64 + 3.13 fails (`sem_timedwait` undeclared). Master has 3.13 fixes, but no release. | Pin Python **3.12** (`requires-python = ">=3.12,<3.13"`, `.python-version` = `3.12`). Alternative if 3.13 is a must: `supriya-midi` (nanobind RtMidi, wheels 3.10–3.14), different API. |
| mido + rtmidi | mido **1.3.3**; extra `mido[ports-rtmidi]` pins `python-rtmidi~=1.5.4` (OK). mido's rtmidi backend calls `ignore_types(False, False, True)`: SysEx and **MIDI clock are passed through**, active sensing is dropped. | Filter by `msg.type` (ignore `clock`, `start`, `stop`, `sysex`). |
| Virtual ports | RtMidi supports virtual ports on CoreMIDI (macOS) and ALSA/JACK, not on Windows. mido: `mido.open_output("Riyaz Fake Keyboard", virtual=True)`. The app sees it as an input. | `tools/fake_player.py` OK. Keep matcher tests independent of CoreMIDI (feed events directly), so most tests run without MIDI. |
| Hot-plug | RtMidi re-queries CoreMIDI on each `get_ports()`. Some reports say new devices do not appear when the CoreMIDI client lives in a thread without a run loop. | Test in Phase 1 with the real cable. Fallback: create a new `rtmidi.MidiIn()` for each 2-s poll; if that fails, run the poll on the main (Cocoa) run loop. |
| Thread handoff | rtmidi callbacks run on a CoreMIDI thread; uvicorn runs an asyncio loop in another thread. | Stamp `time.perf_counter()` in the callback, then `loop.call_soon_threadsafe(queue.put_nowait, evt)`. |
| WebSocket | `uvicorn` without `[standard]` has **no WebSocket library**. FastAPI WebSocket routes then fail ("Unsupported upgrade request"). | Add `websockets` (17.4) to deps; add `--collect-all websockets`. |
| WKWebView + localhost | Reference apps already load `http://127.0.0.1:PORT` in WKWebView. `ws://127.0.0.1:PORT/ws` is same-origin, no mixed content. | OK. |
| Web Audio autoplay | WKWebView starts `AudioContext` as `suspended` until a user gesture. | Call `await Tone.start()` in the first click (for example the setup "Start" button). Show "Click to turn on sound" if the context is still suspended. |
| Audio formats | WebKit decodes MP3 and AAC well. Ogg Vorbis support in WebKit is limited. | Use the **MP3** Salamander files only. |
| Web MIDI | Not in WebKit/Safari. Plan already routes MIDI through Python. | OK. |
| App Nap / throttling | macOS can throttle timers of a background app; WKWebView throttles `requestAnimationFrame` when the window is hidden. | During a session, call `NSProcessInfo.processInfo().beginActivityWithOptions_reason_(...)` (pyobjc is already a pywebview dependency). Pause the song when the window is hidden. |
| PyInstaller + rtmidi | Module name is `rtmidi` (C extension `rtmidi._rtmidi`). mido loads its backend by string (`mido.backends.rtmidi`), so PyInstaller does not see it. mido reads its version with `importlib.metadata`. | Add `--collect-all mido --collect-all rtmidi --hidden-import mido.backends.rtmidi --copy-metadata mido --collect-all websockets`. Check the frozen app with the fake player in Phase 1, not only in Phase 6. |
| Port choice | DocKit uses 8010, passport 8000. | Use `PORT` env, default `8020`. If busy, fall back to a free port (DocKit has no fallback). |
| Latency target | Localhost WebSocket round trip is usually 1–3 ms. A 20 ms end-to-end target (callback → UI paint) is realistic. Measure UI receipt with `performance.now()` mapped through the synced clock. | OK. |

---

## 3. Libraries and versions (question 2)

| Package | Latest (date) | Python | Licence | Notes |
|---|---|---|---|---|
| mido | 1.3.3 (2024-10) | ≥3.7 | MIT | Active repo (commits Nov 2026). |
| python-rtmidi | 1.5.8 (2023-11) | wheels ≤3.12 | MIT | See Section 2. |
| pywebview | 6.2.1 (2026-04) | ≥3.8 | BSD-3 | Pulls pyobjc 13 (~8 MB). |
| fastapi | 0.162.6 (2026-11-13) | **≥3.11** | MIT | |
| uvicorn | 0.54.0 (2026-09) | ≥3.10 | BSD | Add `websockets`. |
| websockets | 17.4 | ≥3.11 | BSD | |
| pyinstaller | 6.22.3 (2026-09) | 3.8–3.15 | GPL + exception | hooks-contrib 2026.10. |
| pretty-midi | 0.2.11.post0 (2026-07) | — | MIT | 5.6 MB wheel (bundles a soundfont). Avoid unless needed. |
| **Tone.js** (npm `tone`) | **15.1.22** (latest tag, 2025-04); `next` = 15.5.67 | — | MIT | Vendor `https://cdn.jsdelivr.net/npm/tone@15.1.22/build/Tone.js` (345 KB, already minified). Save as `static/vendor/tone.min.js` or `Tone.js`. API: `new Tone.Sampler({urls: {A1: "A1.mp3", C2: "C2.mp3", "D#2": "Ds2.mp3", ...}, baseUrl: "/static/samples/salamander/", release: 1, onload})`; `.toDestination()`; `triggerAttack(note, time, velocity)`, `triggerRelease(note, time)`, `triggerAttackRelease(note, dur, time, velocity)`; `await Tone.loaded()`; `await Tone.start()`. |
| Salamander samples | `https://tonejs.github.io/audio/salamander/` (repo `Tonejs/audio`) | — | **CC-BY 3.0**, Alexander Holm (Yamaha C5) | 30 MP3 files (A0–C8, in minor thirds: A, C, Ds, Fs): **2.0 MB total** (ogg set 6.9 MB). For 61 keys (MIDI 36–96) plus margin, A1–C7 = ~22 files, **~1.5 MB**. `tonejs-instrument-piano-mp3` npm (15.6 MB) is not needed. Download with curl; no node needed. |
| **basic-pitch** | **0.4.0 (2024-08)**, no newer release | see note | Apache-2.0 | On Darwin: requires `tensorflow-macos<2.15.1` when Python > 3.11; tensorflow-macos has no cp312 wheel, so **install fails on 3.12/3.13**. Open issues/PRs (2025–2026) for 3.12, none merged. The wheel ships `nmp.onnx`, `nmp.tflite`, `nmp.mlpackage`, TF SavedModel (all <1.1 MB). Backend order at import: TF → CoreML → TFLite → ONNX. Fix: `[tool.uv] override-dependencies = ["tensorflow-macos; sys_platform == 'never'"]`; it then uses `coremltools` 9.0 (cp312 arm64 wheel) or `onnxruntime` 1.32.0 (22.5 MB). Also pins `resampy<0.4.3`; resampy 0.4.2 imports `pkg_resources`, which **setuptools 82 removed** → pin `setuptools<81` in that group. Test with `librosa<1.0` first (librosa 1.0.1 is new, needs ≥3.12; basic-pitch was written for 0.10/0.11). |
| piano_transcription_inference | 0.0.6 (2025-01) | ≥3.6 | MIT (LICENSE added 2026-11-12) | Needs torch + torchlibrosa. Default checkpoint path is `~/piano_transcription_inference_data/` and it downloads with `os.system('wget ...')` — **wget is not on macOS**. Always pass `checkpoint_path=models/...` and download the file in Python. Checkpoint: **172 MB** (Zenodo 4034264). |
| demucs | **4.1.0 (2026-07-11)** | ≥3.10 | MIT | Maintained again by A. Défossez (repo `adefossez/demucs`; `facebookresearch/demucs` is archived). Models now on Hugging Face (`adefossez/HTDemucs`, `955717e8.safetensors` **84 MB**). Set `HF_HOME=./models/hf`. Reads wav/mp3/ogg/aac itself; ffmpeg optional. Needs torch (arm64 wheel **139 MB**, ~400 MB installed). |
| librosa | 1.0.1 (2026-11-12) | **≥3.12** | ISC | For 3.12 OK. Pulls numba + llvmlite (~45 MB). |
| pianoplayer | 3.0.2 (2026-03) | ≥3.9 | **MIT** | OK to compare against (dev-only). Core deps: `rich` only. |
| torch | 2.15.0 | ≥3.11 | BSD | cp312 arm64 139 MB. |

---

## 4. Yamaha YPT-320 facts (question 3)

Sources: PSR-E323/YPT-320 Owner's Manual (en, b0) and Data List (MIDI implementation chart, 2008).

- **61 keys, C1–C6**, Touch Response (manual p.74). Plan mapping 36–96, middle C = 60 is consistent with Yamaha "C3 = 60" naming. Calibrate anyway.
- **Connectors:** MIDI IN/OUT (5-pin DIN), SUSTAIN, PHONES/OUTPUT, DC IN 12V. **No USB.** Manual: "A Yamaha UX16 or similar USB-MIDI interface ... will be necessary" (p.58). Class-compliant cables (UM-ONE mk2) need no driver on macOS.
- **Note off:** chart says Note OFF transmitted = x → it sends **Note On with velocity 0**. Velocity 1–127.
- **Sustain:** **CC 64 is transmitted** (o). Footswitch FC4/FC5. Do not press it at power-on (polarity is detected then).
- **Other transmitted messages:** Program Change, CC 0/32, 7, 10, 72, 91, 93, SysEx, **MIDI Clock and Start/Stop (FA/FC when the style starts/stops)**, Active Sensing. Transmit channels: 1–16.
- **PC mode** (hold [DEMO] > 1 s): OFF (default) = Local On, Song Out On, Style Out On, Keyboard Out On. PC2 = Local Off, Keyboard Out On, Song/Style Out Off. PC1 = Local Off, External Clock On, Keyboard Out Off (do not use — no notes are sent).
  - Effect: in PC mode OFF, **preset style and accompaniment notes go out on MIDI** too. Dual and Split voices can add notes on other channels.
  - Action: learn the main channel during calibration ("Press middle C"); accept notes on that channel only; ignore clock/realtime; tell the user "Do not start a style or a song on the keyboard during practice". Note: in PC mode OFF the keyboard's own sound stays on (wanted).
- **Local control:** Function setting "Local ON/OFF", and **CC 122 is received** (`Bn 7A 00` = off, `Bn 7A 7F` = on). The app can set Local Off for "Mac sound only" and must send Local On at exit.
- **Transpose** −12..+12 and Octave settings exist (p.49). Calibration covers them.
- **Touch Response** can be switched off ([TOUCH] button) → all velocities fixed. The touch calibration step must detect "all 8 velocities equal" and say "Press the TOUCH button to turn touch on."
- **Polyphony 32.** Keep demo output to the keyboard thin (melody + simple chords).
- C1 + C#1 held together act as a remote-control shortcut for "Digital Music Notebook" (p.60). Rare, but avoid songs that hold both lowest keys.

---

## 5. Public-domain check of built-in songs (question 4)

Composition level only; all arrangements are self-written. Do not copy any modern published arrangement or recording.

| Song | Status | Note |
|---|---|---|
| Mary Had a Little Lamb | Clear | 1830 poem; tune Lowell Mason, 1830s. |
| Twinkle Twinkle | Clear | French tune 1761; Taylor poem 1806. |
| Ode to Joy | Clear | Beethoven 1824. |
| Jingle Bells | Clear | Pierpont 1857. |
| Happy Birthday | Clear (US since 2016; EU since 2017; India since 2007) | Tune "Good Morning to All" (Hill sisters 1893). Lyrics: US court (Marya v. Warner/Chappell, 2015–16) — no valid copyright. Patty Hill d. 1946. |
| London Bridge, Au Clair de la Lune, Frère Jacques | Clear | Traditional, 18th c. or older. |
| When the Saints | Clear | Traditional spiritual. Avoid copying Armstrong-style arrangements. |
| Amazing Grace | Clear | Newton 1779; tune "New Britain" 1829/1835. |
| Minuet in G (Petzold) | Clear | 1725. |
| Für Elise | Clear | 1810. |
| Canon in D | Clear | Pachelbel, c.1700. |
| Greensleeves | Clear | 16th c. |
| Scarborough Fair | Clear, with care | Traditional ballad and tune. Use the plain traditional tune only; not the Simon & Garfunkel "Canticle" counter-melody or Martin Carthy's arrangement. |
| Danny Boy | Clear | "Londonderry Air" (published 1855); Weatherly words 1913, d. 1929. |
| **Saare Jahan Se Achha** | **Not clear → remove** | Words: Iqbal 1904 (PD). The familiar **melody is by Pandit Ravi Shankar (1945)**, d. 2012 → protected in India until 2073 (life + 60). The older slow tune is not the one users know. |
| **Vande Mataram** | **Not clear → remove** (or use Tagore's tune only) | Poem: Bankim Chandra 1875/1882 (PD). Many tunes: Jadunath Bhattacharya (lost), Tagore 1896 (Tagore d. 1941 → PD in India since 2002), Raicharan Mukhopadhyay, Paluskar, and the well-known film version by **Hemanta Mukherjee (Anandamath, 1952; d. 1989 → protected)**. The tune users know is probably protected. Plan rule says exclude when unclear. |
| Raghupati Raghav Raja Ram | Probably clear (medium confidence) | Words from Lakshmanacharya's "Sri Nama Ramayanam" (traditional); Gandhi's edit. Familiar tune credited to **V. D. Paluskar (d. 1931)** → PD in India (since 1992) and elsewhere. Avoid film versions (for example 1954 "Jagriti", 1998 "Kuch Kuch Hota Hai"). Write the source in `DECISIONS.md`. |

Result: 17 songs remain. Level 4 loses "Saare Jahan Se Achha" and Level 8 loses "Vande Mataram". Replace them with clearly PD items (for example "Oh! Susanna", Foster 1848, for Level 4 and "Auld Lang Syne", traditional, for Level 8), or put Indian song ideas in `IDEAS.md` after a separate check.

---

## 6. Public-domain MIDI for Phase 3 acceptance (question 5)

- **Mutopia Project** (mutopiaproject.org): licence is set **per piece** and shown on each piece page: Public Domain dedication, CC BY, CC BY-SA (old MutopiaBSD is phased out). MIDI files are generated from the same LilyPond source; take the piece's licence as the MIDI licence.
- For test fixtures in the repo, choose pieces marked **"Public Domain"** (or CC BY with credit in `tests/fixtures/LICENSES.md`). Avoid CC BY-SA in the repo (share-alike on derived files).
- Good candidates (single piano, easy): Petzold Minuet in G (BWV Anh. 114), Clementi Sonatina Op. 36 No. 1, Beethoven Für Elise, Satie Gymnopédie No. 1, Bach Prelude in C (BWV 846). Check each licence at download time.
- Also write 1–2 fixtures with `mido` in the tests (type-0 one-track file, type-1 two-track file, drum channel 10, tempo change) so the importer tests do not depend on downloads.

---

## 7. Project-local dependencies (question 6)

All of these can stay inside `piano-coach/`:

```sh
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
export UV_PYTHON_PREFERENCE=only-managed   # do not use /Library/Frameworks Python 3.13
export HF_HOME="$PWD/models/hf"            # demucs models
export TORCH_HOME="$PWD/models/torch"
uv python install 3.12
uv sync                                    # .venv in project
```

- Put these exports in the Makefile (`export UV_CACHE_DIR := ...`) or `.envrc`; add `.uv-cache/ .uv-python/ models/ .venv/` to `.gitignore`.
- Python 3.12: uv-managed, project-local. Wheels exist for all Phase 1–4 deps → **no compiler** needed.
- Node: **not needed.** Get `Tone.js` and the Salamander MP3s with `curl` (a `make vendor` target) and commit them in `static/`.
- Models: `./models/` (basic-pitch model ships inside its wheel; piano-transcription checkpoint → `models/piano_transcription/…pth` via explicit `checkpoint_path`; demucs → `HF_HOME`).
- M4A/AAC decode: use macOS built-in `afconvert -f WAVE -d LEI16 in.m4a out.wav`. No ffmpeg needed.
- App data: `~/Library/Application Support/Riyaz/` (outside the project, by design, as plan says). Tests must use a temp dir via env var (`RIYAZ_DATA_DIR`).

Global items (already present or optional):
- `uv` (`~/.local/bin/uv`, present), Xcode CLT (present, not needed with 3.12), `gh` (present, for `make release-mac`), `git`.
- Ollama (Phase 6, optional, global app; not installed). The app must work without it.
- The USB-MIDI cable (hardware).

---

## 8. Download sizes and memory (question 7)

| Phase | What | Download | Disk |
|---|---|---|---|
| 1–4 | uv Python 3.12 | ~17 MB | ~70 MB |
| 1–4 | Python deps (fastapi, uvicorn, websockets, pydantic, pywebview + pyobjc, mido, python-rtmidi, pyinstaller, pytest) | ~30 MB | ~130 MB |
| 1–4 | Tone.js + Salamander MP3 (A1–C7 subset / full 30) | 0.35 MB + 1.5–2.0 MB | ~2.5 MB |
| **1–4 total** | | **~50 MB** | **~200 MB** (`.app` ~60–90 MB) |
| 5 light | basic-pitch + coremltools/onnxruntime + librosa + numpy + scipy + numba/llvmlite + scikit-learn + soundfile/soxr + resampy + mir-eval | **~130 MB** | ~450 MB |
| 5 heavy (optional) | torch + demucs + htdemucs model (84 MB) + piano_transcription_inference + torchlibrosa + checkpoint (172 MB) | **~400 MB** | ~1 GB |
| **5 total** | | **~530 MB** | **~1.5 GB** |

Memory (16 GB Mac is enough):
- Phases 1–4: Python + WKWebView ~250–400 MB.
- basic-pitch: <1 GB for a 4-min song.
- demucs htdemucs on CPU/MPS: ~3–6 GB peak for a 4-min song (lower with smaller `segment`). Run it in a subprocess so memory is returned.
- piano_transcription_inference: ~1–2 GB.

---

## 9. Risks not in the plan (question 8)

1. **Python version trap:** reference apps use 3.13; rtmidi needs ≤3.12. A copy of DocKit's `.python-version` breaks `uv sync`.
2. **Keyboard sends style/song/clock data** on MIDI in PC mode OFF (Section 4) → false "extra notes". Filter by channel and type.
3. **Touch Response off** gives constant velocity → dynamics feedback is wrong.
4. **Local control left off** (after a crash in "Mac sound only" mode) → keyboard is silent. Send Local On at exit and on next start; add a setup tip.
5. **Stuck notes** when the cable is pulled during play → send "all keys up" in the matcher on disconnect.
6. **Audio stack in the `.app`:** the plan says "optional download" but gives no method. A frozen PyInstaller app cannot `pip install` later. Proposal: bundle only the light stack (basic-pitch via CoreML/ONNX, ~150 MB more in the `.app`) or keep audio import dev-only in v1; make demucs/piano-transcription a dev-mode extra (`uv sync --group audio-ml`). Write the choice in `DECISIONS.md`.
7. **basic-pitch is not maintained for new Python** (last release 2024-08). Keep its use behind one function so it can be replaced (for example by calling `nmp.onnx` directly with onnxruntime).
8. **`pkg_resources` removal** (setuptools 82) breaks resampy 0.4.2 if imported.
9. **WKWebView autoplay** blocks sound until a click; the first lesson must start with a click.
10. **App Nap / hidden window** throttling during play-along (Section 2).
11. **CoreMIDI hot-plug** may not refresh port lists from a background thread (Section 2).
12. **Unsigned app on macOS 27:** `xattr -cr` works today; Apple may tighten Gatekeeper. No MIDI entitlement is needed for an unsigned, non-sandboxed app.
13. **Port conflict** with DocKit (8010) / passport tool (8000) if run together; use 8020 + fallback.
14. **Salamander CC-BY** needs visible credit (About screen; plan has it) and a `static/samples/salamander/README` copy.
15. **Song list legal check** removes 2 Indian songs, which the user may value; tell the user.

---

## Proposed changes (numbered)

1. Use **Python 3.12**: `.python-version` = `3.12`, `requires-python = ">=3.12,<3.13"`, `UV_PYTHON_PREFERENCE=only-managed`. Revisit when python-rtmidi ≥1.6 has cp313 wheels.
2. Add **`websockets`** to dependencies and `--collect-all websockets` to the Makefile/spec.
3. PyInstaller flags: add `--collect-all mido --collect-all rtmidi --hidden-import mido.backends.rtmidi --copy-metadata mido`. Test the frozen `.app` with the fake player at the end of Phase 1.
4. MIDI service: accept notes only on the channel learned at calibration; drop `clock`, `start`, `stop`, `sysex`, `program_change`; treat `note_on` vel 0 as off; handle CC 64; send CC 122 Local On at exit if the app turned it off.
5. Setup text: add "Do not start a style or song on the keyboard", "Set PC mode to OFF (hold DEMO)", and "Press TOUCH to turn touch on" (when velocities are all equal).
6. Hot-plug: verify in Phase 1; fallback = new `MidiIn()` per poll, or poll on the main run loop.
7. Audio: `await Tone.start()` on first click; vendor `tone@15.1.22/build/Tone.js`; use **MP3** Salamander A1–C7 (~1.5 MB), MIDI-to-name map `D#` → `Ds.mp3`. Add a `make vendor` curl target. No node.
8. Default port `8020` with `PORT` env and a free-port fallback.
9. Phase 5 deps in a separate group: `audio` = `basic-pitch`, `coremltools` (or `onnxruntime`), `librosa<1.0` (test 1.0 later), `setuptools<81`, with `[tool.uv] override-dependencies = ["tensorflow-macos; sys_platform == 'never'"]`. `audio-ml` (optional) = `torch`, `demucs>=4.1`, `piano_transcription_inference`. Set `HF_HOME`/`TORCH_HOME` to `./models`; pass `checkpoint_path` to piano transcription and download it in Python (no wget).
10. Decide and write in `DECISIONS.md` how audio import ships in the `.app` (light stack bundled, heavy stack dev-only in v1).
11. Decode M4A with macOS `afconvert` to WAV before transcription.
12. Built-in songs: **remove Saare Jahan Se Achha and Vande Mataram**; keep Raghupati Raghav with the Paluskar source note; replace the 2 removed songs with clearly PD songs (for example "Oh! Susanna", "Auld Lang Syne"). Update the Level 4 and Level 8 rows.
13. Phase 3 acceptance: use Mutopia pieces marked Public Domain (or CC BY with credit); also generate fixtures with mido.
14. Prevent App Nap during a session (`NSProcessInfo.beginActivityWithOptions_reason_`) and pause when the window is hidden.
15. Tests: set `RIYAZ_DATA_DIR` to a temp folder; keep matcher/feedback tests free of CoreMIDI; only `tests/test_midi_virtual.py` uses virtual ports (skip if CoreMIDI is not available).
16. pianoplayer is MIT; allowed as a dev-only comparison.

---

## Sources

- PyPI JSON API: python-rtmidi, mido, pywebview, fastapi, uvicorn, websockets, pyinstaller, basic-pitch, piano-transcription-inference, demucs, librosa, pianoplayer, torch, onnxruntime, coremltools, tensorflow, setuptools.
- python-rtmidi issue #217 (3.13 support): https://github.com/SpotlightKid/python-rtmidi/issues/217
- basic-pitch backend selection: https://github.com/spotify/basic-pitch/blob/main/basic_pitch/__init__.py ; 3.12 issues on the same repo.
- setuptools NEWS (pkg_resources removed): https://github.com/pypa/setuptools/blob/main/NEWS.rst
- resampy 0.4.2 `pkg_resources` import: https://github.com/bmcfee/resampy/blob/0.4.2/resampy/filters.py
- mido rtmidi backend: https://github.com/mido/mido/blob/main/mido/backends/rtmidi.py
- piano_transcription_inference: https://github.com/qiuqiangkong/piano_transcription_inference ; checkpoint https://zenodo.org/record/4034264
- demucs (maintained): https://github.com/adefossez/demucs ; model https://huggingface.co/adefossez/HTDemucs
- Tone.js npm: https://www.npmjs.com/package/tone ; Salamander: https://github.com/Tonejs/audio/tree/master/salamander
- Yamaha PSR-E323/YPT-320 Owner's Manual: https://usa.yamaha.com/files/download/other_assets/6/313656/psre323_en_om_b0.pdf
- Yamaha PSR-E323/YPT-320 Data List: https://de.yamaha.com/files/download/other_assets/8/313998/psre323_en_dl_a0.pdf
- Mutopia licence page: https://www.mutopiaproject.org/legal.html
- Sare Jahan se Accha (Ravi Shankar tune): https://en.wikipedia.org/wiki/Sare_Jahan_se_Accha ; https://www.nationalheraldindia.com/entertainment/sare-jahan-se-achcha-was-composed-by-ravi-shankar
- Vande Mataram tunes: https://en.wikipedia.org/wiki/Vande_Mataram ; https://www.songsofyore.com/vandya-vande-mataram-the-story-of-a-song-perennial/
- Raghupati Raghava Raja Ram: https://en.wikipedia.org/wiki/Raghupati_Raghava_Raja_Ram ; https://en.wikipedia.org/wiki/Vishnu_Digambar_Paluskar
