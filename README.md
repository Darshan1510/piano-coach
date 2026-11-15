# Riyaz

A daily piano-practice coach for a MIDI keyboard (built for the Yamaha YPT-320) on macOS.
Riyaz is Hindi/Urdu for "daily practice".

Phase 1: MIDI connection, setup and calibration, a live 61-key keyboard on the screen with note
names and chord names, and a Mac piano sound.
Phase 2: 6 built-in songs (Levels 1-2), falling notes with finger numbers and a hand
outline, Watch and Play (wait) modes, hands, speed, the click, count-in and "Repeat a part".
Phase 3a: MIDI file import (Songs → "Import a song") with track choice, hand split,
automatic fingering, chords, key and a difficulty check on each imported song card.
Phase 3b: Today (a daily session: warm-up, song, review, "Find the key", with a
timer and an end summary), Learn (keyboard basics and the song ladder, Levels 1-3, with skill
moments inside the songs), Words (the music words that you learned), streak with a weekly
streak freeze, daily goal, practice calendar and an optional Mac reminder (Settings).
Phase 4: "Play along" (the song does not wait; points, stars, green/yellow/red keys,
one tip at a time), "Continue from here" when you stop, after-run findings with a small picture
of the place, "Show me" and a practice button, automatic speed changes, spaced repetition of
learned song parts, a skill model, and the Progress page (skills, calendar, results over time).
Phase 5a: song simplifier (easy versions for your level), song editor, audio import.
Phase 5b (this version): course Levels 4-8 (13 more songs: black keys, keys together, patterns,
longer runs, rhythm feels keherwa and dadra) with their skill moments and words, and "Ear games"
(echo, the jump between 2 keys, shapes of 3 keys, happy or sad, what comes next, find the tune,
add keys together to a tune, jam). The daily practice picks one game for your weakest skill.
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
Imported songs: `~/Library/Application Support/Riyaz/songs/<id>.json` with the original `<id>.mid`.

```sh
uv run tools/fake_player.py --song imported --hands RL --follow http://127.0.0.1:8020   # wait mode, imported songs
uv run tools/fingering_report.py            # automatic fingering vs the built-in songs
uv run tools/make_test_midi.py              # make the test MIDI files in tests/data/midi/
```

Course and daily session (the app must run):

```sh
uv run tools/fake_player.py --basics  http://127.0.0.1:8020            # do the keyboard basics
uv run tools/fake_player.py --session http://127.0.0.1:8020 --minutes 10   # a whole daily session
uv run tools/fake_player.py --autoplay http://127.0.0.1:8020 --until 600   # play what the window asks for
```

Play-along (the app must run):

```sh
uv run tools/fake_player.py --song all --mode play --follow http://127.0.0.1:8020   # exact timing: >= 98 points
uv run tools/fake_player.py --song twinkle-twinkle --mode play --follow http://127.0.0.1:8020 \
    --runs 3 --jitter-ms 150 --shift-ms -80 --slip-rate 0.1 --hard-bar 3 --seed 1   # errors -> findings
```

Ear games (the app must run; Level 8 opens all games):

```sh
uv run tools/fake_player.py --drill all --follow http://127.0.0.1:8020 --answer correct   # each game: 100 points
uv run tools/fake_player.py --drill jam --follow http://127.0.0.1:8020 --answer wrong     # low points
uv run tools/make_ladder_songs.py --check   # the Level 4-8 song files match the tool (hand-written notes)
```

With a real keyboard connected, test with the fake port only: start the app with
`RIYAZ_PORT_FILTER="Riyaz Fake Keyboard"` and `RIYAZ_DATA_DIR=<a temp folder>`.

Progress (sessions, song results, course, words, practice time) is in
`~/Library/Application Support/Riyaz/riyaz.sqlite3`.

`music21` is in the dev group only (test oracle). It is never in `Riyaz.app`.

### Audio import (Phase 5a)

The audio packages are in the uv group `audio` (basic-pitch with its CoreML model, librosa, numpy,
scipy; about 116 MB download, all in `.venv`). `uv sync` installs them. Without them
(`uv sync --no-group audio`) the app works; only audio import is off.

```sh
uv run tools/make_test_audio.py ode-to-joy /tmp/ode.wav     # a test WAV from a song (known notes)
uv run python -m riyaz.importers.audio_worker IN.wav OUT.json   # the worker alone (progress on stdout)
```

No demucs, torch or piano-transcription model (not installed; see `DECISIONS.md`, Phase 5a).

## Build

```sh
make build-mac      # dist/Riyaz.app (uses Riyaz.spec), with audio import: about 290 MB
make build-mac-base # dist/Riyaz.app without audio import: about 45 MB
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
