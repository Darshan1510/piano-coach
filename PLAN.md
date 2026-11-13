# Riyaz — Piano Coach — Build Plan

Working name: **Riyaz** (Hindi/Urdu for "daily practice"). The user can change the name.

This file is the complete build specification for a daily piano-practice app. A new Claude Code session reads this file and builds the software. Read the whole file before you write code.

---

## 0. Instructions for the build session

1. Read this whole file first.
2. Build the project in this folder: `piano-coach/` (the folder that holds this file).
3. Use the same stack and packaging as the user's earlier apps, **DocKit** and **passport-photo-tool** (the DocKit project and the passport-photo-tool project, next to this project). Read their `main.py`, `Makefile`, `*.spec`, `install.sh`, and `README.md` first. Copy their patterns (FastAPI + pywebview + PyInstaller, `static/` frontend, `uv`, `install.sh`, GitHub release flow).
4. Build one phase at a time (Section 12). Do not start a phase until the previous phase passes its acceptance checks.
5. After each phase, run the tests and the acceptance checks. Report the results to the user.
6. Tell the user before each large download. Give the size.
7. Write all user-facing text in the app in ASD-STE100 Simplified Technical English: short sentences, active voice, simple words, commands for instructions.
   The user is a complete beginner. Follow the beginner word rules in Section 7.4: never show a music term that the user has not learned yet, and always show *where* on the screen, not only a name.
8. If a library in this plan does not work as described, choose the nearest working option. Write the change in `DECISIONS.md` with the reason.
9. Do not add features that this plan does not list. Put new ideas in `IDEAS.md`.

---

## 1. Goal

Take one adult beginner (no piano experience) to **amateur level** on a Yamaha YPT-320 keyboard, with short daily practice.

"Amateur level" for this app means the user can:

- Play a simple song with melody in the right hand and chords in the left hand.
- Play the 4 most common chord progressions in 6 keys, with simple accompaniment patterns.
- Learn a new easy-to-medium song (for example a Bollywood or pop melody with chords) in about one week.
- Find a simple melody by ear and add chords to it.

The app does these things:

1. Gives a **daily session** (15–25 minutes): warm-up, new skill, song practice, review, and an intuition exercise.
2. Shows the keys to press as **falling notes** onto an on-screen keyboard, with **finger numbers** and a **moving hand outline**.
3. **Listens** to the keyboard through MIDI and checks each note: correct key, timing, length, and touch (velocity).
4. **Nudges** the user: live color feedback, short tips, and automatic changes (slower tempo, hands separate, loop the hard bar).
5. Builds **musical intuition**: intervals, chord shapes, patterns, and playing by ear.
6. Imports songs from **MIDI files** and from **audio files** (rough transcription).
7. Records progress, streaks, and skill levels.

### User decisions (already made — do not ask again)

| Question | Decision |
|---|---|
| Input | **USB-MIDI cable only.** No microphone note detection. |
| Songs | Built-in free (public-domain) songs, **plus** MIDI import, **plus** audio transcription. |
| Hand display | Falling notes + finger numbers + hand outline. No 3D hands, no camera. |
| Notation | **Keys only.** No sheet music. Show note names and chord names only. |
| Learning style | **Song-first.** Learn through songs. Only a 10-minute "Keyboard basics" start before the first song. Skills are taught inside songs, when needed (Section 8). |
| App type | Mac desktop app, same stack as DocKit (pywebview window around a local web UI). |

---

## 2. Hardware

### Keyboard: Yamaha YPT-320

- 61 keys with touch response (velocity).
- Connections: PHONES/OUTPUT, DC IN 12V, **MIDI IN / MIDI OUT (5-pin DIN)**, SUSTAIN (footswitch jack).
- The YPT-320 has **no USB port**. It shares its owner's manual with the PSR-E323; the manual lists the UX16 USB-MIDI interface as an optional accessory.
- Key range in Yamaha naming: C1–C6. Yamaha names middle C "C3". In MIDI numbers this is normally **36–96**, with middle C = **60**. The keyboard's TRANSPOSE and OCTAVE settings can shift the MIDI output, so the app must calibrate (Section 6.2).
- Check these facts against the owner's manual (Yamaha website) during Phase 1, and write the result in `DECISIONS.md`.

### Things the user must buy

| Item | Price | Notes |
|---|---|---|
| USB-MIDI cable (required) | $15–40 | Good choice: Roland UM-ONE mk2 (~$40) or Yamaha UX1 (if available). Cheap generic cables (~$15) often drop notes. |
| USB-C adapter (if the cable is USB-A) | ~$8 | MacBook Air M4 has only USB-C ports. |
| Sustain footswitch (optional, Phase 6) | ~$15–25 | Yamaha FC5 or FC4. The app reads it as MIDI CC 64 (if the keyboard sends it — check). |

### Cable connection (common mistake)

On most USB-MIDI cables, the plug marked **"IN"** goes into the keyboard's **MIDI OUT** jack. The plug marked **"OUT"** goes into the keyboard's **MIDI IN** jack. The labels describe the cable side, not the keyboard side. Show a diagram of this in the app setup screen. Some cables use other labels; the setup test (Section 6.2) finds errors.

### Two-way MIDI

- Keyboard MIDI OUT → Mac: the app hears the user.
- Mac → keyboard MIDI IN: the app can play demo notes **on the keyboard's own speakers**. This is a useful "listen first" option. Mac speaker playback (Web Audio) is the default; keyboard playback is a setting.

---

## 3. Market review — feature tiers

Apps reviewed (from general knowledge; the build session does not need to research again): Simply Piano, Flowkey, Yousician, Playground Sessions, Skoove, Piano Marvel, Synthesia, Pianote.

Common features: falling notes or sheet music, wait mode, tempo control, loops, hands-separate practice, MIDI connection, daily goals and streaks, song library, structured courses, scoring.

Gaps that this app fills: free and local; the user's own songs (MIDI + audio import); Bollywood-friendly chord courses; real coaching from error patterns, not only a score; intuition and ear exercises.

### Basic (Phases 1–3) — the minimum useful app

- MIDI connection, calibration, live on-screen keyboard.
- Falling-notes player with finger numbers, hand colors, and hand outline.
- **Wait mode**: the song stops until the user presses the correct key(s).
- Tempo slider (25%–150%), loop a section, right hand / left hand / both hands.
- Metronome with count-in.
- Keyboard basics + song ladder Levels 1–3 with skill moments (Section 8).
- Built-in public-domain songs.
- MIDI file import with hand split and automatic fingering.
- Daily session, streak, daily goal.

### Pro (Phases 4–5)

- **Play-along mode** with scoring: note accuracy, timing (early/late), note length, evenness of touch.
- **Error analysis and nudges** (Section 7): finds error patterns and gives specific tips and automatic practice changes.
- **Smart practice**: spaced repetition of hard sections; automatic tempo steps (slow → target).
- Course Levels 4–7: chords, progressions, accompaniment patterns, scales.
- **Intuition exercises**: intervals by ear, chord quality by ear, play-back-the-melody, find-the-key.
- **Audio import**: MP3/WAV → notes (rough), then the song editor.
- **Song simplifier**: makes an easy version of any song (melody + simple chords).
- Song editor: fix notes, hands, fingers; set loop sections.
- Progress page: skill radar, practice calendar, scores over time.

### Advanced (Phase 6)

- Course Levels 8–10: inversions, arpeggios, sustain pedal, rhythm patterns, play by ear, simple improvisation over a chord loop.
- **Lead-sheet mode**: show only melody + chord names; the user makes the left-hand part (as real amateur players do).
- **Transpose trainer**: play a learned song in a new key.
- Dynamics coaching (velocity: soft/loud, melody louder than accompaniment).
- **Local LLM coach** (optional, Ollama): weekly summary and plain-language tips from the error data.
- Free-play recorder: record, play back, and export to MIDI.

---

## 4. Architecture

```
pywebview window (WKWebView)
  └── static/ web UI (HTML + JS + Canvas)   <── WebSocket ──>  FastAPI backend (Python)
        - falling notes renderer                                 - MIDI in/out (python-rtmidi)
        - on-screen keyboard + hands                             - matcher (score follower)
        - Web Audio piano (Tone.js Sampler)                      - error analysis + nudges
        - course / session / progress UI                         - song import (MIDI, audio)
                                                                 - fingering + hand split
                                                                 - SQLite (progress, songs)
```

### Main decision: MIDI goes through Python, not the browser

pywebview on macOS uses WKWebView (Safari engine). WKWebView does **not** support the Web MIDI API. So:

- The backend reads MIDI with `python-rtmidi` (via `mido`).
- The backend sends each note event to the UI over a WebSocket (target: under 10 ms delay on localhost).
- The backend does the matching and scoring, so that the result does not depend on UI frame rate.

### Timing

- The backend stamps each MIDI event with `time.perf_counter()` when the rtmidi callback runs.
- The UI and backend share one song clock. The backend sends `clock_sync` messages; the UI keeps an offset (ping/pong, take the median of 5).
- The backend is the source of truth for "song time". The UI draws from the synced clock at 60 fps.
- Audio output delay (Web Audio) is not important for the user's own notes (the user hears the keyboard's own sound). It matters for the metronome and backing: add a "latency calibration" setting (tap with the click).

### Technology choices

| Part | Choice | Notes |
|---|---|---|
| Python | 3.11–3.13 with `uv` | Same as DocKit. Check audio-transcription packages for version support. |
| App shell | `pywebview` + FastAPI + Uvicorn | Copy DocKit's `main.py` pattern. |
| Packaging | PyInstaller (`.spec` + `Makefile`), `install.sh` | Copy DocKit. Add `--collect-all rtmidi` / `mido`. |
| MIDI live | `mido` + `python-rtmidi` | Input, output, virtual ports (for tests). |
| MIDI files | `mido` (read/write); `pretty_midi` only if needed | |
| Music theory | Own small module (`theory.py`): note names, intervals, chord detection, keys | Avoid `music21` (large). Use it only if a feature needs it; write why. |
| Fingering | Own dynamic-programming fingering (Section 5.3) | Option: compare with the open-source `pianoplayer` package; check its license first. |
| Audio transcription | Spotify `basic-pitch` (Apache-2.0) for general audio; option: ByteDance `piano_transcription_inference` for solo-piano audio | Phase 5. Check Python version support and model size. |
| Source separation | `demucs` (MIT) to remove vocals/drums before transcription | Phase 5. Large (~1–2 GB with PyTorch). Optional step. |
| Frontend | Plain HTML/JS, Canvas 2D (or PixiJS if Canvas is too slow) | No build step, same as DocKit `static/`. |
| Piano sound | Tone.js `Sampler` with Salamander Grand Piano samples (CC-BY 3.0), bundled locally | No network at runtime. Credit in About screen. |
| Storage | SQLite (`sqlite3` stdlib) in `~/Library/Application Support/Riyaz/` | Songs, attempts, progress, settings. |
| Optional coach | Ollama HTTP API, `qwen3:4b` | Phase 6. App must work without it. |
| Tests | `pytest` | Virtual MIDI port as a simulated player. |

---

## 5. Song data

### 5.1 Internal song format (JSON)

```json
{
  "id": "ode-to-joy-easy",
  "title": "Ode to Joy (easy)",
  "source": "builtin | midi | audio",
  "bpm": 100,
  "time_signature": [4, 4],
  "key": "C major",
  "level": 1,
  "notes": [
    {"id": 0, "pitch": 64, "start": 0.0, "dur": 1.0, "hand": "R", "finger": 3, "vel": 80}
  ],
  "chords": [{"start": 0.0, "dur": 4.0, "name": "C"}],
  "sections": [{"name": "Line 1", "start": 0.0, "end": 16.0}],
  "hand_positions": [{"hand": "R", "start": 0.0, "thumb_pitch": 60}]
}
```

- `start` and `dur` are in **beats**, not seconds. Tempo changes only the playback speed.
- `hand_positions` gives the hand outline: where the thumb sits, for each position change.

### 5.2 Hand split (imported MIDI)

1. If the MIDI file has 2 piano tracks (or channels), use track 1 = right hand, track 2 = left hand. Let the user swap them.
2. If it has 1 track: split with a dynamic-programming method. Cost terms: distance from a moving split point (start at middle C), hand span over 1 octave, more than 5 notes at once in one hand, hand jump distance. Keep each hand continuous over time.
3. The user can change the hand of any note in the song editor.

### 5.3 Automatic fingering

Imported songs have no fingering. Make it with dynamic programming (Viterbi over finger choices), for each hand separately:

- States: the finger (1–5) for each note; for chords, a finger set.
- Cost rules (based on Parncutt et al. 1997 and later work): comfortable span for each finger pair; penalty for crossing without thumb; penalty for thumb on black keys in fast passages; penalty for finger 4 after 3 on the same direction stretch; small penalty for position changes; reward for staying in a 5-finger position.
- Beginner mode (Levels 1–3): prefer fixed 5-finger positions with few position changes, even if a pianist would play it another way.
- Output: `finger` per note and `hand_positions`.
- Test: built-in songs with hand-written fingering. The automatic fingering must match at least 70% of notes. Report the result.

### 5.4 Built-in songs (public domain / traditional only)

Write these by hand in the JSON format with correct fingering. Each song has an easy version (one hand, 5-finger position) and, where possible, a harder version (both hands, chords).

Mary Had a Little Lamb, Twinkle Twinkle Little Star, Ode to Joy, Jingle Bells, Happy Birthday (public domain in the US since 2016), London Bridge, Au Clair de la Lune, Frère Jacques, When the Saints Go Marching In, Amazing Grace, Minuet in G (Petzold), Für Elise (opening), Canon in D (chord pattern), Greensleeves, Scarborough Fair, Danny Boy, Saare Jahan Se Achha (Iqbal, 1904, melody), Vande Mataram (traditional melody), Raghupati Raghav Raja Ram (traditional bhajan).

Check the public-domain status of each item (composition and arrangement). Do not include any item when the status is not clear. Write the result in `DECISIONS.md`.

### 5.5 User songs (Bollywood / Hollywood)

- The app does **not** include copyrighted songs.
- The user imports MIDI files or audio files that the user owns or has the right to use, for personal practice.
- Import screen text: "Import a MIDI or audio file. Use only files that you have the right to use."

---

## 6. Live input and matching

### 6.1 MIDI service (`midi_io.py`)

- List input/output ports. Pick the USB-MIDI cable automatically when there is only one input. Remember the choice.
- Hot-plug: check ports every 2 seconds. Show "Keyboard connected / not connected" in the top bar.
- Events to the UI: `note_on` (pitch, velocity, time), `note_off` (pitch, time), `cc` (64 sustain).
- `note_on` with velocity 0 = `note_off` (many keyboards send this).

### 6.2 Setup and calibration

1. Setup screen: cable diagram (Section 2), with these numbered steps:
   1. Turn on the keyboard.
   2. Connect the cable plug marked **OUT** to the keyboard's **MIDI IN** jack.
   3. Connect the cable plug marked **IN** to the keyboard's **MIDI OUT** jack.
   4. Connect the USB-C end to the Mac.
   5. Click "Find my keyboard". The app selects the "USB MIDI" device. macOS needs no driver and no extra program.
   Show a note: "Most connection problems come from swapped plugs. If the test fails, swap the 2 plugs on the keyboard."
2. Test: "Press any key." If no event comes in 10 seconds: "Swap the IN and OUT plugs on the keyboard." Then: "Set TRANSPOSE to 0 and OCTAVE to 0 on the keyboard."
3. Calibration: "Press middle C" (show its place: the C near the middle of the keyboard, left of the 2 black keys). Store the offset between the received pitch and 60. Apply it to all input.
4. Touch: "Play 4 notes soft, then 4 notes loud." Store the user's velocity range. Use it to scale dynamics feedback.
5. Optional: MIDI output test: "The app plays a note on your keyboard. Did you hear it?"

### 6.3 Practice modes

| Mode | How it works | Use |
|---|---|---|
| **Watch** | The app plays the song. Falling notes, hand outline, and finger numbers move. Sound on Mac or keyboard. | Listen first |
| **Wait** | Notes fall and stop at the hit line until the user presses all correct keys for that moment. No timing score. | Learn the notes |
| **Play-along** | The song moves at the set tempo. The app scores each note. | Build timing |
| **Loop** | Repeat one section. Optional auto tempo step: +5% after 3 clean runs. | Fix hard parts |
| **Free play** | Live keyboard, note and chord names, record + play back. | Explore, intuition |

Each mode supports right hand only, left hand only, or both. In single-hand practice, the app can play the other hand (accompaniment on).

### 6.4 Matcher (`matcher.py`)

Wait mode:

- At each stop point, the expected set = all notes that start at this time for the active hands.
- Continue when all expected keys are down at the same time (chord) or in order within 300 ms.
- Wrong key: mark it red on the keyboard; do not continue. Log the error.

Play-along mode (score following):

- Each expected note has a time window. Thresholds in `config.py`:
  - **Perfect**: within ±50 ms (at the current tempo).
  - **Good**: within ±120 ms.
  - **Late / early**: within ±250 ms.
  - **Missed**: no matching press inside ±250 ms.
- Match each input `note_on` to the nearest unmatched expected note with the same pitch inside the window.
- An input with no match = **extra note**. Check whether it is a neighbor key (±1 or ±2 semitones) of an expected note at that moment = **wrong note (likely slip)**.
- Note length: compare `note_off` time to the expected end. "Short" if held less than 60% of the length (for notes ≥ 1 beat).
- If the user stops or restarts (more than 2 seconds without input), pause the song and show "Continue from here?" with the stop point marked on the falling-notes view (Section 7.4).
- Scores: accuracy %, timing % (perfect + good), length %, and a 0–100 total. Show stars (1–3).

### 6.5 Hand outline display

- From `hand_positions` and fingering: draw a simple half-transparent hand shape over the keyboard, with 5 finger dots above the keys of the current position.
- Highlight the finger for the next note. Show the finger number inside each falling note.
- Before a position change, show an arrow and "Move your right hand to G" one beat early.
- Colors: right hand = blue, left hand = green (change in settings; check for color-blind safe contrast).

---

## 7. Feedback and nudges

### 7.1 Live (during play)

- Key turns green (correct), red (wrong), yellow (correct but late/early).
- Small text above the keyboard, at most one at a time, at most one each 4 seconds. Examples:
  - "Use finger 3 here." (when the wrong key is the neighbor that the planned finger 3 would play)
  - "Wait for the beat." (3 early notes in a row)
  - "Keep the note down longer." (2 short notes in a row)

### 7.2 After each run

The app looks at the error log of the run and shows at most 3 findings, most important first.

The messages below are the **beginner versions** (Levels 1–3). After the user learns a term (Section 7.4), the app can add it, for example "This part (bar 7) is hard for you." Every finding that names a place in the song shows a **preview**: a small picture of the falling notes for that part, with the wrong notes in red, and a "Show me" button that plays that part.

| Pattern | Rule | Message (beginner) | Action button |
|---|---|---|---|
| Hard spot | ≥ 2 errors in the same bar in 2 of the last 3 runs | "This part is hard for you." + preview | "Practice this part slowly" (loop at 60% speed) |
| Rushing | Mean timing error < −40 ms over ≥ 8 notes | "You play too early. Wait for the click." | "Play with the click" |
| Dragging | Mean timing error > +60 ms | "You play too late. Keep up with the click." | "Make it slower" |
| Hand problem | One hand's accuracy is ≥ 20 points lower | "Your left hand needs more practice." | "Left hand only" |
| Coordination | Each hand alone ≥ 85%, both hands < 70% | "Each hand is good. Now play both hands together, slowly." | "Both hands, half speed" |
| Hand move | Errors cluster on notes right after a hand position change | "Move your hand to the new place earlier." + preview of the move | "Practice the move" (short loop) |
| Chord missing key | Chord played with a missing key ≥ 2 times | "Press all 3 keys together." + the 3 keys glow | "Practice these 3 keys" |
| Uneven touch | Velocity SD high in a passage that should be even | "Press all keys with the same force." | — |
| Short notes | Length score < 60% | "Hold the key down until the falling note ends." | — |

### 7.3 Automatic adapt (setting: on by default)

- 3 failed runs (score < 60) in a row: lower tempo by 15% (minimum 40%).
- 3 clean runs (score ≥ 90): raise tempo by 5–10% up to 100%, then offer the next step (both hands, next section, next song).
- Song done at 100% tempo with score ≥ 85: mark "learned". Schedule review with spaced repetition (Section 9.3).

### 7.4 Beginner word rules

The user starts with no music knowledge. Music words like "bar", "beat", "tempo", or "chord" mean nothing on day 1. Follow these rules in all screens, tips, and lessons.

**Rule 1 — Show the place, do not only name it.** When a message refers to a part of the song, also:
- Highlight that part on the falling-notes view (a colored band across the notes).
- Show the preview picture (Section 7.2).
- If the song has lyrics or known words, add them: "the part at 'Happy birthday dear…'".
- Use plain names for song parts: "Part 1", "Part 2" (the song's `sections`), and "this part".

**Rule 2 — Use plain words until the lesson teaches the term.** Each music term has an "unlock" lesson. Before that lesson, the app uses the plain word.

| Term | Plain word before unlock | Unlock lesson | Explanation card text (example) |
|---|---|---|---|
| finger number | — | Level 1 | "Your thumb is 1. Your little finger is 5. This is the same on both hands." |
| middle C | "the C in the middle" | Level 1 | "Find the 2 black keys near the middle. The white key just left of them is middle C." |
| beat | "the click" | Level 2 | "A beat is the steady pulse of the song. The click plays one beat. Tap your foot with it." |
| rest | "a pause" | Level 2 | "A rest is a time with no keys. Count it like a beat." |
| tempo | "speed" | Level 2 | "Tempo is the speed of the song. A lower tempo is slower." |
| bar (measure) | "this part" / "Part 2" | Level 3 | "A bar is a small group of beats, usually 4. Songs are made of bars, like a sentence is made of words. The thin lines across the falling notes show where each bar starts." |
| hand position | "where your hand sits" | Level 1 | "Put one finger on each key. Your hand stays here until the arrow tells you to move." |
| sharp / flat | "the black key right of F" | Level 4 | "A black key has two names. F sharp is the black key just right of F." |
| chord | "these 3 keys together" | Level 5 | "A chord is 3 or more keys played at the same time. Most chords use every other white key: play one, skip one, play one, skip one, play one." |
| major / minor | "happy sound / sad sound" | Level 5 | "A major chord sounds bright. A minor chord sounds sad or soft." |
| progression | "chord pattern" | Level 6 | "A progression is a list of chords that repeat. Many songs use the same 4 chords." |
| scale | "the 8-key walk" | Level 7 | "A scale is a walk up or down the keys of one key family, from one C to the next C." |
| interval | "the jump between 2 keys" | Level 3 | "An interval is the distance between two keys. Count the white keys from one to the other." |

**Rule 3 — Explain on first use.** When a term appears for the first time after its unlock, show a small explanation card (from the table) with a "Got it" button. After that, the term has a dotted underline. Tap it to see the card again.

**Rule 4 — Glossary page.** A "Words" page lists all unlocked terms with the card text and a short demo (the app plays or highlights an example).

**Rule 5 — Visual bar lines appear with the term.** Before Level 3, the falling-notes view does not show bar lines. From Level 3, thin lines show each bar, with small numbers. This connects the word "bar" to what the user sees.

**Rule 6 — Test the text.** In Phase 4, write a test that scans all message strings and lesson texts for locked terms. A message for a Level-N lesson must not use a term with an unlock level above N, unless the text explains the term in the same message.

---

## 8. Course (song-first, keys only, beginner → amateur)

**User decision: learn through songs.** The course is a ladder of songs. The app teaches each skill at the moment a song needs it, not in separate theory lessons. The only exception is a short "Keyboard basics" start (8.1), which the user needs before the first song.

### 8.1 Keyboard basics (prerequisite, one time, about 10 minutes)

Three short interactive steps. Each step uses the real keyboard; no reading.

| Step | What the user learns | How the app checks |
|---|---|---|
| B1. Find your way | Black keys come in groups of 2 and 3. The white key left of each group of 2 is C. Middle C is the C near the middle. Left = lower sound, right = higher sound. | "Press every C." "Press middle C." "Press a key in a group of 3." |
| B2. Fingers and hand shape | Finger numbers 1–5 (thumb = 1, both hands). Curved fingers, relaxed wrist, sit at the middle of the keyboard. | "Press middle C with finger 1." The app shows a finger number; the user presses the matching key in the 5-finger position. |
| B3. Read the screen | How falling notes work: a note falls, touches the line, then press the key; a long note = hold the key; colors = hands. Soft and loud touch. | A 10-note demo in wait mode. "Play 2 keys soft, then 2 keys loud." |

The user can repeat basics at any time from the "Words" page.

### 8.2 Skill moments (just-in-time teaching)

A **skill moment** is a 30–90 second mini-lesson inside a song.

1. Before the first place in a song that needs a new skill, the song stops.
2. The app shows: "New: [plain name of skill]." Then a short demo with the hand outline.
3. The user tries only that move, 3 times, slowly.
4. The song continues from just before that place.

Each song in the ladder lists its new skills. The app adds a skill moment for each new skill. Examples: "New: move your hand", "New: the black key", "New: 3 keys together (chord)", "New: thumb goes under".

A skill moment also unlocks the matching music term (Section 7.4).

### 8.3 Song ladder

Each **level** is a group of songs. A song is "done" at 100% speed with a score of 80 or more. A level is done when all its songs are done. The user can also skip forward; the app warns which skills the song needs.

| Level | Songs (built-in) | New skills taught inside these songs |
|---|---|---|
| 1. First songs (right hand) | Mary Had a Little Lamb (3 keys), Ode to Joy (RH), Twinkle Twinkle (RH) | Stay in the 5-finger position; hold long notes; repeat a key; small jumps |
| 2. Keep the beat | Au Clair de la Lune, Frère Jacques, London Bridge | The click (beat); pauses (rests); steady speed |
| 3. Left hand joins | Ode to Joy (LH single notes), Twinkle (LH single notes), Frère Jacques (both hands) | Left hand finger numbers; one hand, then both hands; bar lines appear |
| 4. Move and black keys | Jingle Bells (in F, one black key), When the Saints, Saare Jahan Se Achha (melody) | Move your hand to a new place; first black key; sharp/flat names |
| 5. First chords | Happy Birthday (LH chords C, F, G), Amazing Grace (LH chords), Raghupati Raghav (LH chords) | 3 keys together; happy vs sad chords (major/minor); change chord on time |
| 6. Chord patterns | Canon in D pattern (simple), "4-chord loop" song template (C–G–Am–F) used for imported songs | The same 4 chords repeat in many songs; play chords in other keys |
| 7. Longer runs | Minuet in G (simple), Ode to Joy (full, both hands) | Thumb goes under; finger goes over; play 8 keys in a row (scale) |
| 8. Rhythm patterns | Scarborough Fair, Greensleeves, Vande Mataram (melody + LH pattern) | Broken chords; LH patterns; Bollywood rhythm feels (keherwa = 4 beats, dadra = 6 beats) |
| 9. Smooth and soft | Für Elise (opening), Danny Boy | Pedal; smooth chord changes (inversions); melody louder than LH |
| 10. Your songs | The user's imported Bollywood/Hollywood songs (Section 11) | Melody + chord names only (lead sheet): make your own LH part; play by ear; change key |

### 8.4 Imported songs in the ladder

The user's own songs (Bollywood, Hollywood) are the main reason to learn. Bring them in early, as easy versions.

- **Difficulty check.** For each imported song, compute: notes per second, hand span, black-key count, chords, hand moves, both hands at once, fast runs. Map these to the skill list of the ladder.
- **Playable now.** The song card shows: "You can play the easy version now." or "This song needs: chords, hand moves. You learn these in Level 5."
- **Easy versions by level.** The simplifier (Section 11.2) makes a version that uses only the skills the user has. Example: at Level 1, a 5-finger right-hand melody in C (transposed, with few hand moves). At Level 5, the melody + LH block chords.
- **Skill moments in user songs.** When the user plays a harder version, the app adds skill moments for skills that the user has not learned yet.
- After each level, the app suggests the next version of the user's songs: "Your song 'X' has a new version for your level."

### 8.5 Content

The build session writes the basics, skill moments, and song ladder as JSON in `data/course/`. Each skill moment has: a plain name, a term to unlock (if any), a short instruction text (STE style), a demo (notes + hand positions), and a pass rule (3 correct tries).

---

## 9. Daily practice

### 9.1 Daily session (generated)

Default 20 minutes. The user picks 10, 15, 20, or 30 minutes in settings.

| Block | Share | Content |
|---|---|---|
| Warm-up | 10% | A short pattern taken from the current song (for example its hardest hand move or chord change), slow |
| Song | 60% | Current song from the ladder or an imported song. Skill moments appear inside it (Section 8.2). The hardest part first (from the error data), then a full run |
| Review | 15% | One spaced-repetition item: a part of an old song |
| Intuition | 15% | One ear or pattern exercise that uses notes from the current song (Section 10), for example "Echo" with a phrase of the song |

- A timer and a "Next" button for each block. The user can skip a block.
- At the end: summary card (minutes, new skill, best score, streak).

### 9.2 Habit

- Streak counter (a "streak freeze" for 1 missed day each week).
- Daily goal (minutes). Practice calendar (heat map).
- Optional macOS notification at a set time ("Time for your Riyaz.") through pywebview/`osascript`. Off by default.

### 9.3 Spaced repetition

- Items: song sections, chord drills, scale drills, intuition items.
- Use a simple SM-2 style schedule: score ≥ 85 → interval × 2; score 60–84 → same interval; < 60 → interval = 1 day.

### 9.4 Skill model

Track a 0–100 level for these skills, from scores of the related exercises: note reading (keys), rhythm, right hand, left hand, coordination, chords, scales, ear. Show as a radar chart on the progress page. Use the weakest skills to pick warm-up and intuition exercises.

---

## 10. Intuition exercises

These build "feel" for the keyboard and music without sheet music.

| Exercise | How it works | Level |
|---|---|---|
| Find the key | App names a key ("Play F"). User presses it. Timed. | 1+ |
| Echo | App plays 3–6 notes (in the current position). User plays them back. | 2+ |
| Interval ear | App plays 2 notes. User names the interval (step, skip, 5th, octave) or plays it. | 3+ |
| Chord shape | App names a chord ("D minor"). User plays it. Then in other keys. | 5+ |
| Major or minor | App plays a chord. User answers major/minor. | 5+ |
| Next chord | App plays a progression and stops. User plays the next chord (I–V–vi–?). | 6+ |
| Find the melody | App plays a short known melody (built-in song). User finds it on the keys by ear. | 7+ |
| Add chords | User plays a melody; the app suggests chords (key detection + melody notes); user plays them. | 8+ |
| Jam | App plays a chord loop and drum click. User plays any notes from the scale (scale keys glow). | 8+ |
| Transpose | User plays a learned 4-bar section in another key (keys glow for 1 run, then hidden). | 9+ |

---

## 11. Song import

### 11.1 MIDI import (Phase 3)

1. Read with `mido`. Merge tempo map; convert to beats.
2. Pick tracks: show the track list with note counts and instrument names. Default: piano tracks; skip drums (channel 10).
3. Hand split (Section 5.2), fingering (Section 5.3), chord detection per beat/bar (`theory.py`).
4. Quantize option (1/8, 1/16) for messy files.
5. Detect sections: split at long rests or every 4 bars.
6. Save as JSON; keep the original `.mid` file.

### 11.2 Song simplifier (Phase 5)

Make an easy version of any song:

- **Melody**: the highest note at each time in the right hand ("skyline"), with very short notes removed.
- **Chords**: chord per bar (or per half bar) from all notes; limit to triads; left hand plays a block chord or root note.
- Options: melody only (RH), melody + root notes, melody + block chords, transpose to C or G (fewer black keys), slow version.
- Fingering again for the new version.

### 11.3 Audio import (Phase 5)

Results are rough. The app must say so.

1. User picks an MP3/WAV/M4A file.
2. Optional: `demucs` source separation to remove vocals, drums, and bass (setting; large download).
3. Transcription: `basic-pitch` → MIDI notes. Option: `piano_transcription_inference` when the audio is solo piano.
4. Tempo and beat: from `basic-pitch` output or `librosa.beat.beat_track`.
5. Run the simplifier (11.2). Open the result in the song editor so that the user can fix notes.
6. Screen text: "The app makes a first version of the notes. The version has errors. Listen and fix the notes in the editor."

### 11.4 Song editor (Phase 5)

- Piano-roll view: drag notes, delete, add, change length.
- Change hand and finger for a note or a selection.
- Set sections and loop points; set tempo and key.
- Play from any point.

---

## 12. Phases

### Phase 1 — App shell, MIDI, and live keyboard

- Project skeleton copied from DocKit patterns (`main.py`, `Makefile`, `.spec`, `install.sh`, `README.md`, `pyproject.toml`).
- MIDI service, hot-plug, setup and calibration screens.
- On-screen 61-key keyboard that lights up live keys, with note names and chord names (free play mode).
- Web Audio piano sound (Tone.js Sampler, local samples) for app playback.
- Virtual MIDI port test tool (`tools/fake_player.py`) that plays a song into the app as if from a keyboard.

Acceptance:
1. `uv run main.py` opens the app window.
2. With the virtual port, pressed notes appear on the keyboard in under 20 ms (measure and report).
3. Calibration stores the offset; a shifted fake input (+12) still shows the correct notes.
4. Tests pass.

### Phase 2 — Falling notes, wait mode, built-in songs

- Song JSON format, loader, 6 built-in Level 1–2 songs with hand-written fingering.
- Falling-notes renderer (60 fps on the M4), finger numbers, hand colors, hand outline, position-change arrows.
- Watch mode and wait mode, hand selection, tempo slider, metronome, loop.

Acceptance:
1. The renderer holds 60 fps for a 200-note song (measure and report).
2. The fake player completes wait mode for each built-in song.
3. Wrong keys in wait mode turn red and do not advance.

### Phase 3 — MIDI import, hand split, fingering, course Levels 1–3, daily session

- MIDI import (11.1), hand split (5.2), fingering (5.3).
- Keyboard basics (8.1), skill moments (8.2), song ladder Levels 1–3 (8.3), difficulty check and "playable now" for imported songs (8.4).
- Daily session generator (9.1), streak, daily goal, SQLite progress.

Acceptance:
1. Import 3 public-domain MIDI files (for example from the Mutopia Project) and play them in wait mode.
2. Fingering test result ≥ 70% (Section 5.3). Report.
3. A daily session runs from start to end with the fake player.

### Phase 4 — Play-along, scoring, error analysis, nudges

- Play-along matcher (6.4), scores, stars.
- Live feedback (7.1), after-run findings (7.2), automatic adapt (7.3).
- Spaced repetition (9.3), skill model (9.4), progress page.

Acceptance:
1. Fake player with exact timing scores ≥ 98.
2. Fake player with added errors (random ±150 ms timing, 10% wrong neighbor keys, one hard bar) gets the correct findings: the hard bar, the slips, and rushing or dragging when the timing shift is one-sided.
3. Automatic tempo changes work as specified.

### Phase 5 — Course Levels 4–8, intuition, simplifier, audio import, editor

- Song ladder Levels 4–8 with skill moments. Intuition exercises (Section 10) for these levels.
- Easy versions of imported songs by level (8.4), using the simplifier.
- Song simplifier (11.2), song editor (11.4).
- Audio import (11.3). Tell the user the download sizes before this step.

Acceptance:
1. The simplifier turns an imported 2-hand MIDI file into a playable Level-5 version (melody + block chords).
2. Audio import runs on a public-domain recording and gives an editable song.
3. Each intuition exercise has a test with the fake player.

### Phase 6 — Advanced

- Song ladder Levels 9–10: lead-sheet mode, transpose trainer, sustain pedal (CC 64), dynamics coaching.
- Free-play recorder with MIDI export.
- Optional Ollama coach: weekly summary from the progress data (JSON only, no audio). The app must work when Ollama is not running.
- Release build: `make build-mac`, `install.sh`, GitHub release flow (same as DocKit).

Acceptance: the release `.app` installs with `install.sh` on the user's Mac and connects to the keyboard.

---

## 13. Project layout

```
piano-coach/
  PLAN.md  DECISIONS.md  IDEAS.md  README.md
  pyproject.toml  Makefile  Riyaz.spec  install.sh
  main.py                       (pywebview + FastAPI start, as in DocKit)
  riyaz/
    config.py                   (thresholds, paths)
    midi_io.py                  (ports, events, hot-plug, output)
    clock.py                    (song clock, UI sync)
    matcher.py                  (wait + play-along matching, scores)
    feedback.py                 (live tips, after-run findings, adapt rules)
    theory.py                   (notes, intervals, chords, keys)
    fingering.py                (DP fingering)
    handsplit.py                (DP hand split)
    importers/midi_import.py
    importers/audio_import.py   (Phase 5)
    simplify.py                 (Phase 5)
    course.py                   (levels, lessons, tests)
    session.py                  (daily session, streak, spaced repetition)
    skills.py                   (skill model)
    db.py                       (SQLite)
    coach.py                    (Phase 6, Ollama)
  static/
    index.html  app.js  style.css
    js/renderer.js  js/keyboard.js  js/hands.js  js/audio.js  js/ws.js
    vendor/tone.min.js
    samples/salamander/         (piano samples, CC-BY)
  data/
    songs/*.json
    course/*.json
  tools/fake_player.py
  tests/
```

---

## 14. Out of scope

- Microphone note detection (user chose the cable only).
- Sheet music (user chose keys only).
- 3D hands and camera hand tracking (user chose falling notes + fingers).
- Copyrighted songs in the app.
- iOS / Windows builds (Windows only if the DocKit Windows pattern works without extra work; not required).
- Accounts, cloud sync, social features.

---

## 15. Risks

| Risk | Effect | Action |
|---|---|---|
| Cheap USB-MIDI cable drops notes | Wrong scores | Recommend a known cable; add a "MIDI test" that counts lost note-offs (stuck notes) |
| Keyboard TRANSPOSE/OCTAVE not 0 | All notes wrong | Calibration step + warning when many "wrong by 12" errors occur |
| Automatic fingering is not natural | User learns bad habits | Beginner mode prefers fixed positions; hand-written fingering for built-in songs; editor to fix |
| Audio transcription is poor for dense songs | Unusable result | Simplifier + editor; clear warning text; prefer MIDI import |
| Web Audio delay in WKWebView | Metronome feels late | Latency calibration setting |
| Large packages (demucs, PyTorch) make the `.app` very big | Slow install | Make audio import an optional download, not bundled in the base `.app` |
| Public-domain status not clear for some songs | Legal problem | Include only songs with a clear status; write the check in `DECISIONS.md` |
