# Riyaz

A daily piano-practice coach for a MIDI keyboard (built for the Yamaha YPT-320) on macOS.
Riyaz is Hindi/Urdu for "daily practice".

Phase 1: MIDI connection, setup and calibration, a live 61-key keyboard on the screen with note
names and chord names, and a Mac piano sound.
Phase 2 (this version): 6 built-in songs (Levels 1-2), falling notes with finger numbers and a hand
outline, Watch and Play (wait) modes, hands, speed, the click, count-in and "Repeat a part".
See `PLAN.md` and `PROGRESS.md`.

## Install (release build)

```sh
curl -LsSf https://raw.githubusercontent.com/Darshan1510/piano-coach/main/install.sh | sh
```

The installer puts `Riyaz.app` in `~/Downloads` and opens it. Releases start in Phase 6.

If macOS says the app is "damaged": the app is not signed. Run `xattr -dr com.apple.quarantine ~/Downloads/Riyaz.app`.

## You need

- A USB-MIDI cable (for example Roland UM-ONE mk2). The YPT-320 has no USB port.
- The cable plug marked **OUT** goes into the keyboard's **MIDI IN**. The plug marked **IN**
  goes into the keyboard's **MIDI OUT**. The app setup screen shows a diagram.

## Project-local environment

Everything stays in this folder. Nothing goes into a global Python, Homebrew, or your shell profile.

| What | Where | Set by |
|---|---|---|
| Python 3.12 (uv-managed) | `.cache/python/` | `UV_PYTHON_INSTALL_DIR` (Makefile, `env.sh`) |
| uv package cache | `.cache/uv/` | `cache-dir` in `pyproject.toml` + `UV_CACHE_DIR` |
| Packages | `.venv/` | `uv sync` |
| PyInstaller cache | `.cache/pyinstaller/` | `PYINSTALLER_CONFIG_DIR` (Makefile, `env.sh`, and `Riyaz.spec` if not set) |
| Test data (removed after each run) | `.cache/test-data/` | `tests/conftest.py` |
| Raw downloads (Tone.js, samples) | `vendor-downloads/`, copied to `static/` | `make vendor` |

- `make <target>` always loads these values (exports at the top of the `Makefile`).
- For a manual shell, load them first: `. ./env.sh`
- `pyproject.toml` sets `python-downloads = "manual"`, so uv never downloads Python to a global folder.
  A plain `uv run main.py` uses the existing `.venv` and needs no exports.

## Run from source

```sh
make setup          # first time: Python 3.12 into .cache/python, packages into .venv
uv run main.py      # app window
uv run main.py --browser    # in the default browser
uv run main.py --server     # server only
PORT=8123 uv run main.py    # other port (default 8020; if busy, the app takes a free port)
RIYAZ_DATA_DIR=/tmp/riyaz-data uv run main.py   # other data folder (tests use this)
RIYAZ_PORT_FILTER="Riyaz Fake" uv run main.py   # see only MIDI ports whose name starts with this text
```

App data (settings, calibration): `~/Library/Application Support/Riyaz/`.

## Test without a keyboard

```sh
make test                                   # uv run pytest
uv run tools/fake_player.py --repeat 0      # virtual port "Riyaz Fake Keyboard" plays a tune
uv run tools/fake_player.py --shift 12      # as if OCTAVE/TRANSPOSE were +12
uv run tools/fake_player.py --noise         # also clock, start/stop, sysex, other channel
uv run tools/measure_latency.py             # key-to-app delay (app must run)
uv run tools/fake_player.py --song ode-to-joy                       # play a song's right hand in time
uv run tools/fake_player.py --song all --follow http://127.0.0.1:8020 --wrong 2
                                            # wait mode for every song in the running app (2 wrong keys each)
uv run tools/make_test_song.py              # 200-note test song in .cache/test-songs/
RIYAZ_EXTRA_SONG_DIR=.cache/test-songs uv run main.py   # show test songs in the Songs list
```

Songs are JSON files in `data/songs/` (format: `PLAN.md` 5.1; `start` and `dur` in beats).

## Build

```sh
make build-mac      # dist/Riyaz.app (uses Riyaz.spec)
make release-mac VERSION=v0.1.0   # build + GitHub release with gh (Phase 6)
```

## Clean

```sh
make clean          # remove build/, dist/, the zip, caches of pytest and Python
make distclean      # also remove .venv/, .cache/ (Python, uv, PyInstaller) and vendor-downloads/
```

`make distclean` removes everything that this project installed. To also remove the files that
macOS and the app write outside this folder:

```sh
rm -rf ~/Library/Application\ Support/Riyaz                 # app settings and calibration
rm -rf ~/Library/WebKit/local.riyaz.app ~/Library/Caches/local.riyaz.app   # web view data (Riyaz.app)
```

(When you run from source, WebKit uses `~/Library/WebKit/python3` and `~/Library/Caches/python3`.
Other Python apps with a pywebview window, for example DocKit from source, share these folders.)

## Credits

- Piano sound: Salamander Grand Piano by Alexander Holm, CC BY 3.0 (`static/samples/salamander/README.md`).
- Tone.js 15.1.22, MIT (`static/vendor/README.md`).
