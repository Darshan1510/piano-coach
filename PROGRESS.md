# Progress

## Status

- **Stage:** Phase 4 review fixes (2026-11-14), after Phase 4 (2026-11-14): play-along, scores, live feedback, after-run findings, automatic adapt, spaced repetition, skill model, Progress page. Not committed (the user reviews, then commits). Before: Phase 3, commit 81efb00.
- **Next:** Phase 5 (course Levels 4-8, intuition exercises, simplifier, audio import, song editor).

## Phase 4 review fixes (2026-11-14)

Details and reasons: `DECISIONS.md` "Phase 4 review fixes". Not committed.

- Loop play-along: a first-note press up to 250 ms before the wrap counts for the next pass; a late last-note press after the wrap counts for the pass before (`practice.py` `_prev`/`_next`/`_route`).
- Loop passes: `data.loop_pass` is saved; passes stay out of the run history (findings, adapt, coordination) and the Progress chart.
- Pause back (hidden window) in play-along rewinds the play matcher: replayed notes are not extra notes.
- Latency calibration: Settings card "Tap with the click" (8 clicks, median offset, 0-300 ms, ≥ 5 taps, even taps), `riyaz/tapcheck.py`, `/api/settings/latency` (+ `/start`, `/finish`, `/reset`); play-along takes the offset away from each key time; the click is scheduled `outputLatency` early when the browser gives it. `fake_player.py --tap URL`.
- Matcher: earliest same-key note, but the nearest when the earliest is > 120 ms away and a later one is within 120 ms; "miss" notes do not take a press.
- Reviews count only at 100% speed with the ladder hands. Finding actions with no place keep the current part. Progress "No results yet" as `.sr-only` text. Comments fixed (config.py, matcher.py).

### Results

`uv run pytest`: **298 passed** (291 in 20 s + `tests/test_midi_virtual.py` 7 alone in 36 s; 10 new tests in `tests/test_play.py`, the loop test rewritten). `make build-mac`: OK, **42 MB**.

| Check | Result | Evidence |
|---|---|---|
| 1. Exact fake player ≥ 98 | **Pass: 100 every time** | Real CoreMIDI + source app: 9/9 songs (6 R, Ode LH, Twinkle LH, Frère both hands) = 100, 0 missed, mean error 0.1-0.4 ms. Frozen app: Ode to Joy 100 (0.2 ms). |
| 2. Errors → findings | **Pass** | Real CoreMIDI, ±150 ms, 10% slips, hard bar 3, shift −80/0/+80, 2 songs × 3 shifts × seeds 10/20/30, 2 runs each = 18 cases: hard bar 18/18, slips classified 18/18, slip finding 9/9 (cases with ≥ 3 slips), rushing/dragging 10/12 (misses: Twinkle +80 seed 20 mean +49.4 ms, Ode +80 seed 30 mean +54.9 ms; below the 60 ms rule), false timing 0/6. Fake clock: `test_findings_hard_bar_slips_rushing` (slips assert now unconditional, seed 1 = 4 slips). |
| 3. Automatic speed changes | **Pass** | Unit + server tests as Phase 4 (all pass); `test_loop_auto_step_after_3_clean_passes` rewritten for the delayed pass result; `test_loop_passes_stay_out_of_history_and_progress` (3 passes < 60 + 1 run < 60: no "slower"). |
| +80 ms user delay | **Pass** | Source app, constant +80 ms (±20 ms): no calibration Ode mean +80.2 ms, Twinkle +82.5 ms → "dragging"; `fake_player --tap` +80: offset 78.6 ms (8 taps, spread 9 ms); with calibration Ode +1.7 ms, Twinkle +3.9 ms → no finding. Frozen app: Twinkle +82.5 → dragging; tap 79.0 ms; then +3.5 ms, no finding. Fake clock: `test_latency_calibration_takes_the_offset_away`. |
| Fix tests | **Pass** | `test_loop_early_press_at_the_wrap_and_late_press_after_it` (−100 ms first note, +100 ms last note: 3 passes 100, 0 extra, 0 missed; −200 ms = early, not extra), `test_pause_back_in_play_along_rewinds_the_notes` (100), `test_fast_repeated_keys_after_a_missed_note_take_the_nearest`, `test_nearest_only_when_the_later_note_is_within_good`, `test_a_missed_note_is_closed_after_a_speed_change`, `test_review_counts_only_at_full_speed_with_the_ladder_hands`, `test_tap_check_offset_math`, `test_tap_check_through_the_server` (incl. foreign Origin 403). |
| Screenshots | **Done** | Hidden WKWebView, dark + light: "Tap with the click" idle, running (dots), result (real check through the virtual port, 82 ms), failed. No JS errors, no horizontal scroll. The check page turns off the screen animation and transitions (no frames in a hidden window: the screen stayed at opacity 0 and the theme change stopped half way; not an app fault). the scratchpad folder (`phase4-fix/shots/`) |

### Open issues (Phase 4 review fixes)

- WKWebView gives `AudioContext.outputLatency` = undefined (baseLatency 2.7 ms): the click is not moved; the tap check covers the delay. Click sound and the tap check with a real person and the YPT-320 not tested (hidden window: no sound heard).
- The offset is also taken away from the keys when the user plays with the app's notes (no click); one value for all.
- Rushing/dragging with ±150 ms jitter: 10/12 (means of +49 / +55 ms with an 80 ms shift are below the 60 ms rule).
- A loop pass result comes about 250 ms after the wrap (the late window of the last notes).

## Phase 4 (2026-11-14)

Details and reasons: `DECISIONS.md` "Phase 4".

- `riyaz/matcher.py` `PlayMatcher` + `score_of` (windows ±50/±120/±250 ms at the current speed, earliest unmatched same key, extra notes, neighbor slips, short notes, stop point, rewind); `riyaz/practice.py` mode `play` (stop → "Continue from here", Loop passes with +5% auto step, live tips, `span` places); `riyaz/feedback.py` (live tips, 9 patterns + slips, at most 3, adapt, next step); `riyaz/review.py` (SM-2 style); `riyaz/skills.py` (8 skills); `riyaz/course.py` real song-done rule + learned; `riyaz/session.py` review block from the due items, weakest skill picks the warm-up hands; `riyaz/db.py` version 3; `riyaz/server.py` findings + adapt in the `course` event, `GET /api/progress`, options `adapt`/`loop_step`.
- UI: mode "Play along"; green/yellow/red keys; tip line; dashed "Continue from here" line; score card (stars, points, right keys / on time / held long enough), speed message, up to 3 findings with preview (red notes), "Show me", action buttons; warm band on the falling notes for the place (Rule 1); switches "Change the speed for me", "Go faster after 3 good runs"; NAV "Progress" (skill radar + table, calendar, "Play again soon", results over time + table); daily session "Step 1 of 4" / "Skip this step".
- `tools/fake_player.py`: `--mode play`, `--runs`, `--jitter-ms`, `--shift-ms`, `--slip-rate`, `--hard-bar`, `--seed`; `--session` plays play-along steps too.
- No new packages. Real YPT-320 connected: all checks used `RIYAZ_PORT_FILTER` (virtual ports only) and temp data folders.

### Phase 4 acceptance

`uv run pytest`: **288 passed** (281 in 19 s + `tests/test_midi_virtual.py` 7 alone in 35 s; 42 new in `tests/test_play.py`). `make build-mac`: OK, **42 MB**.

| Check | Result | Evidence |
|---|---|---|
| 1. Exact fake player ≥ 98 | **Pass: 100 every time** | Fake clock: `test_exact_fake_player_scores_at_least_98_each_song` (9 songs × each hand choice, all 100, 0 missed, 0 wrong). Real CoreMIDI + running app (`fake_player --mode play --follow`): 11/11 runs = 100 points, 3 stars (6 Level 1-2 songs R, Au Clair RL, Ode LH, Twinkle LH, Frère both hands RL and L); mean timing error 0.1-0.3 ms. Frozen `Riyaz.app --server`: Ode to Joy 100 points (mean error 0.4 ms). |
| 2. Errors → findings | **Pass** | Real CoreMIDI + app, ±150 ms jitter, 10% neighbor slips, hard bar 3, shift −80 / 0 / +80 ms, 2 songs × 3 shifts × 3 seeds = 18 cases (2 runs each; the hard spot needs 2 of the last 3 runs): hard bar found and shown **18/18** (bar 3 each time); slips classified **18/18** (found = sent); "slips" finding **11/11** cases with ≥ 3 slips (shown 11/11); rushing/dragging **11/12** one-sided cases (miss: Ode +80 seed 2, mean +56.8 ms < 60 ms rule), **0/6** false timing findings with no shift. Fake clock sweep (6 songs × 3 shifts × 5 seeds = 90): hard bar 90/90, slips counted 90/90, slip finding 54/54, timing 85/90 (5 misses: means within 40-60 ms of 0 with ±150 ms jitter on 21-29 notes); 8/90 extra "hand move" findings (random slips right after a move). |
| 3. Automatic speed changes | **Pass** | Unit: `test_adapt_3_failed_runs_slower_min_40`, `..._counts_only_runs_at_the_current_speed`, `..._3_clean_runs_faster_up_to_100_then_next_step` (+5, +10 when all ≥ 95, cap 100, next step both hands / next part / whole song / new song), `test_loop_auto_step_after_3_clean_passes` (+5% in Loop), learned at 85 + reviews (`test_learned_song_schedules_reviews`). End to end through the server: `test_adapt_end_to_end_through_the_server` (100% → 3 fails → 85%, 3 clean → 90%, at 100% → next step, setting off → none). Window check (source app, Twinkle at 100% with errors): after the 3rd run < 60 the course event said "slower 85%" and the page set the speed to 85%. |
| Song done / learned | **Pass** | `test_song_done_rule` (play ≥ 80 at 100%; wait mode only Level 1), `test_level_1_to_2_to_3...` (Level 2-3 with play-along; a Level 2 wait run = keys learned only). |
| Spaced repetition, skills | **Pass** | `test_spaced_repetition_schedule` (×2 / same / 1 day, only when due, once a day), `test_session_review_block_uses_the_due_item`, `test_find_key_drill_is_a_review_item`, `test_skill_model_from_results`, `test_weakest_skill_picks_the_warmup_hand`, `test_database_v2_upgrades_to_v3`. |
| Rule 6 | **Pass** | `test_rule_6_feedback_texts` (tips, findings, buttons, speed texts, skill names; no term unlocked and each single term unlocked); the UI scan now covers `progress.js` and the new practice strings. |
| Frozen app | **Pass** | `Riyaz.app --server` (temp data, port filter): exact play-along run 100 points; 2 error runs (Twinkle, ±150 ms, −80 ms, 10% slips, hard bar 3): 66 and 72 points, run 2 findings = hard spot (bar 3) + rushing, live tips "Use finger 5 here.", "Wait for the click.", "Keep the key down longer."; foreign Origin POST 403, bad Host 400. A second fake-player run with the same port name right after the first got no keys (known hot-plug issue, IDEAS.md): the app paused with "stopped" as designed; a new port name worked. |
| WKWebView screenshots | **Done** | Dark + light: play-along live (red neighbor key, "Use finger 5 here."), after-run card (score, speed message, 3 findings with red previews, Show me, action buttons), "Continue from here" stop, Progress at 1280 and 1100 px with results and empty. Fixed after looking: previews blank (drawn only in an animation frame), card taller than the stage (main buttons now above the findings, title + score on one line), old tip left in the banner; Progress (user feedback): radar labels clipped/touching the table, "No results yet" wrapping in every row ("—" + one note), chart not top-aligned, stacking at 1100 px, empty state. the scratchpad folder (`phase4/`) (`shots/`, `shots-pg/`, `shots-empty/`). |

### Open issues (Phase 4)

- Not tested with the real YPT-320 or by a person (timing with a real cable, tips while playing, the 2-second stop rule with a real beginner).
- The check window is hidden (the user was using the Mac; a visible window took real clicks): no animation frames, so the driver draws frames by hand; "Show me" animation and sound not seen/heard.
- Rushing/dragging uses the plan numbers (−40 / +60 ms); with ±150 ms random timing on a short song (20-30 notes) a one-sided shift of 80 ms is found about 11 of 12 times.
- Hand-move finding can fire on random slips right after a move (8/90 in the sweep).
- Findings only after play-along runs (not wait mode). One speed setting for all songs.
- Restart (the user plays the phrase again) is not detected separately.

## Phase 3 review fixes (2026-11-13)

Details and reasons: `DECISIONS.md` "Phase 3 review fixes".

- 3a: consistent time signature / bar when the beat falls back (6/8 fast -> 3/4); note limit on the selected tracks + raw limit on every note_on; stable tempo sort (later event wins); `user_level` selects the fingering mode; program change from a conductor track; "Off / Large steps / Small steps" timing words; normal-mode fingering tuned + a black-key test set.
- 3b: run results saved on a worker thread (not under the practice lock), song list cached; strict term marks with plain words for any locked term; "bar" plain = "group of clicks"; left-hand G text fixed + position-text test; old open sessions closed, session time only for its day and after its start; block timer from server time, paused while hidden; basics tasks keyboard-usable; modal focus trap and focus return; `PRAGMA user_version`.

Results: `uv run pytest` **246 passed** (239 in 19 s + `tests/test_midi_virtual.py` 7 alone in 36 s; 24 new tests). `make build-mac` OK, 42 MB.

| Check | Result | Evidence |
|---|---|---|
| Import 3 PD MIDI files + wait mode (fake player) | **Pass** | Source app, new data folder: Bach (165 notes), La Native (172), Les Graces one track (228); `fake_player --song imported --hands RL --follow --wrong 2 --speed 1.5`: 3/3 PASS (106 / 103 / 114 stops, 2 wrong each, 0 advanced). |
| Fingering report | **Pass** | Beginner: built-in 313/350 = 89.4%, black-key set 129/144 = 89.6% (those passages use normal mode). Normal: built-in 293/350 = **83.7%** (was 69.7%), black-key set 129/144 = 89.6%, together 422/494 = 85.4%. Per song (normal): Mary 100, Ode 100, Twinkle 95.2, Au Clair 55.0, Frère Jacques 82.5, London Bridge 90.6, Ode LH 100, Twinkle LH 73.8, Frère both 85.4; Ode in D 100, scales LH 80, scales RH 80, triads 100. `test_normal_mode_matches_hand_written_fingering` (>= 70%). |
| Daily session end to end (fake player) | **Pass** | Source app: `fake_player --session --minutes 10 --wrong 2`: 4/4 parts, streak 1, session time 47.2 s, wall 47.4 s. Frozen `Riyaz.app --server`: 4/4 parts, 46.9 s / 47.0 s; foreign Origin POST `/api/course/skip` and `/api/session/1/end` 403. |
| WKWebView check | **Pass** | Today: timer goes on after a reload (1:56 left after 3.8 s), stays paused while hidden, server gets `paused`; Import: "Off / Large steps 1/8 / Small steps 1/16"; term card: Tab and Shift+Tab wrap, Escape returns the focus to "Show me"; basics tasks `role=button`, Enter selects and keeps the focus; no `[[` marks on the page; no JS errors. Screenshots: the scratchpad folder (`p3fix/shots/`). |

### Open issues (Phase 3 review fixes)

- Normal-mode fingering: Au Clair de la Lune 55% (no memory of the song's hand position); some scale starts/ends differ from the textbook (no "start or end on the thumb" rule).
- "Part" also names the 4 parts of the daily session ("Part 1 of 4", "Skip this part"), as well as the song parts. Not changed in this fix (one word, one meaning: check with the user).
- The check window gets no animation frames (not in front, `document.hidden` true), so the running timer was checked with a page-side stand-in for "visible". Check by hand.
- 3/8 (or similar) at a very high speed is clamped to 300 beats a minute (plays slower than the file).

## Phase 3b (2026-11-13): course and daily practice

Details and reasons: `DECISIONS.md` "Phase 3b".

- Content `data/course/`: `terms.json` (13 terms, PLAN 7.4 table), `basics.json` (B1-B3, 8 tasks + 10-note demo), `skills.json` (11 skill moments), `ladder.json` (Levels 1-3). New songs: Ode to Joy (left hand), Twinkle (left hand), Frère Jacques (both hands). Level 2 Frère Jacques has one pause now.
- Backend: `riyaz/course.py` (content, level, song done rule, skill moments, terms, skip forward), `riyaz/drill.py` (key checks), `riyaz/session.py` (daily plan, sessions, practice time, streak + freeze, calendar, reminder), `riyaz/db.py` (7 new tables). `practice.py`: skill-moment breaks, `seek`, `loop: false`, `practice_end` + accuracy/clean_stops/section/errors. Server: `/api/course*`, `/api/drill*`, `/api/today`, `/api/habit`, `/api/session/*`, `/api/settings/habit`, `/api/habit/notify-test`, `/api/practice/seek` (all POST with the Origin check, all routes with the Host check). New events `drill`, `drill_hit`, `drill_wrong`, `practice_skill`, `course` (old events unchanged).
- UI: NAV Today, Learn, Words; screens Today (plan, block timer, Next/Skip, summary, streak, goal, calendar), Learn (basics card, levels, skip with warning), Words (cards, Show me, basics again), Keyboard basics (3 steps); skill-moment overlay on Practice (New: …, Show me with the hand outline, Try it 3 times, Continue the song); term cards ("Got it", dotted underline); bar lines with numbers from Level 3; Home "Start today's practice"; top bar streak flame, real minutes, session pill; Settings "Daily practice" (length, goal, song, reminder). `static/js/terms.js`, `drill.js`, `course.js`, `basics.js`, `today.js`.
- `tools/fake_player.py`: `--basics URL`, `--session URL [--minutes N --wrong N]`, `--autoplay URL --until S` (plays each drill step and wait-mode stop that the app asks for).

### Phase 3b acceptance (2026-11-13)

`uv run pytest`: **222 passed** (215 in 19 s + `tests/test_midi_virtual.py` 7 alone in 39 s; 30 new tests in `tests/test_course.py`; the 3 Level 3 songs added to the song, practice and fingering tests). `make build-mac`: OK, **42 MB**, `data/course` (4 files) and 9 songs in the bundle.

| Check | Result | Evidence |
|---|---|---|
| 1. Daily session start to end with the fake player (PLAN Phase 3 acceptance 3) | **Pass** | Source app (port 8123, new data folder, real CoreMIDI port): `fake_player.py --session --minutes 10`: warm-up drill (Ode, 0 wrong) → song (Ode whole song at 100%, accuracy 100%, skill moment "Hold a long note" stopped the song at beat 11.5, 3 tries incl. a 1 s hold, song went on from beat 10, song done) → review (Mary Part 2, played once) → Find the key (10 keys); end summary: new skill "Hold a long note", best 100%, streak 1, 4/4 parts, 48 s. Frozen `Riyaz.app --server` (new data folder): same run with `--wrong 2`: 4/4 parts, 2 wrong keys reported, "Stay where your hand sits" + "Press the same key again" (repeat_key stopped Mary at beat 3.5, resumed at 2), "hand position" unlocked, Mary done, streak 1, 47 s. pytest `test_daily_session_end_to_end_with_fake_keys`. |
| 2. Keyboard basics and a skill moment; term unlocks; card once | **Pass** | `fake_player.py --basics` (CoreMIDI): all 8 tasks (every C, middle C, group of 3, finger 1, right/left finger numbers, 10-note wait demo, soft/loud) → `basics_done: true`, unlocked middle C, finger number. pytest: `test_basics_unlock_terms_and_card_shows_once` (unlocked, `seen` false → POST seen → true; locked terms send no term text), `test_skill_moment_in_a_song_unlocks_its_term`, `test_practice_break_and_seek`. UI: first-use card queue (`terms.firstUse`) shows only unseen cards. |
| 3. Level 1 → 2 → 3, bar lines only from Level 3, streak/freeze | **Pass** | `test_level_1_to_2_to_3_and_bar_lines_only_at_level_3` (server path: 75% / 80% speed not done, 85% done; level ups 1→2→3→4; Frère both hands with one hand not done; `bar_lines` false at 1-2, true at 3; imported cards use the course level). Window: Ode to Joy (left hand) at Level 3 shows bar lines with the bar number. Streak/freeze/calendar with fake dates: `test_streak_counts_days_in_a_row`, `test_streak_freeze_one_day_each_week` (one freeze per week, 2 missed days break, yesterday covered while today is open), `test_calendar_heat_map`; reminder with a fake clock: `test_reminder_once_a_day_after_the_time_and_below_the_goal`. |
| 4. Tests, build, frozen app | **Pass** | 222 passed. Build 42 MB. Frozen app: session start + full session with fake notes (row 1); foreign Origin POST `/api/session/start` 403. |
| 5. Screenshots (WKWebView, dark + light) | **Done** | 33 images: Home, Today (plan, warm-up block, song block, Find the key, summary, session pill on Home), skill moment, Words + card, Learn (+ Level 3), basics (B1, B2), Settings, Level 3 bar lines. No JS errors, no horizontal scroll at 1280 px. Fixed after the first look: the active block was below the fold (now at the top, plan = 4-part strip); the summary tiles wrapped ("Less than 1 minute" → "Less than 1 min", smaller values); the skill card hid its buttons and keyboard (buttons above the keyboard, smaller padding). the scratchpad folder (`phase3b/`) |
| Rule 6 (locked words) | **Pass** | `test_rule_6_course_texts_use_no_locked_term` (all course texts by level), `test_level_titles_use_plain_words`, STE sentence length ≤ 25 words; the Phase 2 locked-word test now scans the 5 new UI scripts, renderer/keyboard and the new error classes. |
| Phase 3a regression | **Pass** | Import La Native (172 notes, card text from the course level) + `fake_player --song imported --hands RL --follow --wrong 2`: PASS (103 stops, 2 wrong, 0 advanced). `fingering_report.py`: beginner 313/350 = 89.4% (9 songs; the 6 old songs unchanged), normal 69.7%. |

### Open issues (Phase 3b)

- Not tested with the real YPT-320 or by a person: skill-moment tries, soft/loud split, hold and pause checks, the reminder notification (osascript was not run in the checks; it is unit-tested with a fake notifier).
- "Song done" uses the wait-mode accuracy (Phase 4 replaces it with the play-along score). Speed above 100% also counts.
- Practice time counts only key presses (gaps < 60 s): watching and reading longer texts do not count.
- ~~The block timer runs on wall time, also when the window is hidden.~~ Fixed (review fixes).
- The Words "Show me" opens the card first (the demo is in the card).
- Hot-plug: fake-player runs one after the other still need a short pause (Phase 3a note).

## Phase 3a (2026-11-13): MIDI import pipeline

Details and reasons: `DECISIONS.md` "Phase 3a".

- `riyaz/importers/midi_import.py`: read with mido (tempo map merged, ticks to beats), track list (note count, instrument, drums), default = piano tracks, drums never default, 1/8 and 1/16 grid, song parts (long pause or every 4 bars), clean-up rules, limits (2 MB, 20000 notes, 30 minutes), clear error texts. Saves `<data dir>/songs/<id>.json` + the original `<id>.mid`.
- `riyaz/handsplit.py` (2 parts + swap; DP split for 1 part), `riyaz/fingering.py` (beginner mode + Parncutt normal mode, hand positions), `riyaz/difficulty.py` (measures, skills, level, card text), `theory.py` (chords per bar, key).
- Server: `POST /api/import/midi`, `POST /api/import/midi/{token}/song` (Origin + Host checks); `GET /api/songs` adds imported songs with the card text.
- UI: "Import a song" on the Songs screen, Import screen (file, tracks with hand and note count, swap, timing grid, name), "Your songs" group with the difficulty text; imported songs open in Practice.
- Tools: `tools/make_test_midi.py`, `tools/fingering_report.py`, `fake_player.py --song ID|imported|FILE.json`.
- music21 in the uv dev group (test oracle only); `Riyaz.spec` excludes it and its packages.

### Phase 3a acceptance (2026-11-13)

`uv run pytest`: **183 passed** (38 s; 59 new). `make build-mac`: OK, **42 MB** (no music21, numpy, Pillow in the app).

| Check | Result | Evidence |
|---|---|---|
| 1. Import 3 public-domain MIDI files, play each in wait mode (fake player) | **Pass** | Source app (`main.py --server`, port 8123): `POST /api/import/midi` for Bach BWV Anh. 120 (2 tracks, 165 notes), La Native (2 tracks, 172), Les Graces one track (1 track both hands, DP split, 228). `fake_player.py --song imported --hands RL --follow … --wrong 2 --speed 1.5`: 3/3 PASS (106 / 103 / 114 stops, 2 wrong keys each, 0 advanced on a wrong key; 43 / 22 / 29 s). Also `--song my-la-native-f2ad24 --hands R` PASS and `--song <json path> --hands L` PASS. Backend: every test file completes wait mode for R, L, both (`test_every_test_file_imports_and_completes_wait_mode`). |
| 2. Fingering test ≥ 70% | **Pass: 93.0%** (214/230) | Beginner mode (Levels 1-3): Mary 26/26 100%, Ode to Joy 30/30 100%, Twinkle 42/42 100%, Au Clair 54/60 90.0%, Frère Jacques 33/40 82.5%, London Bridge 29/32 90.6%. Normal mode (for information): 158/230 68.7%. `tools/fingering_report.py`, `test_fingering_matches_hand_written_fingering`. |
| 3. Tests, build, frozen app | **Pass** | 183 passed. `make build-mac` 42 MB; `find dist/Riyaz.app -iname '*music21*'` empty, no numpy/PIL. Frozen `Riyaz.app --server`: POST import of La Native OK (172 notes, card text), foreign Origin 403, bad file 400 with text; fake player wait mode both hands PASS (103 stops, 1 wrong key, 0 advanced). |
| 4. Screenshots (WKWebView, dark + light) | **Done** | Songs "Your songs" cards with difficulty text, Import step 1, tracks, swapped hands, one track, done card, error text, Practice with an imported song. No JS errors, no horizontal scroll at 1280 px. Fixed after the first look: the timing buttons box was as wide as the column; the page now scrolls to step 2 and to the done card. the scratchpad folder (`phase3a/`) |
| music21 cross-checks | **Pass** | Chord root/quality for 144 chords; key = music21 Krumhansl-Kessler on 8 files, = music21 default key on the 3 PD files; note starts in quarter notes = music21 on the 3 PD files. |
| Hand split (DP) vs real tracks | **Pass** | Bach 99.4%, La Native 100%, Les Graces 95.2% (test needs ≥ 90%). |
| Bad files | **Pass** | Empty, not MIDI, header only, cut file, garbage, zero timing division, 300 randomly damaged files: an error text or a correct song, no crash. |

### Open issues (Phase 3a)

- Imported songs play at one speed (tempo changes are counted, not played).
- ~~Normal-mode fingering only checked by rules (68.7%).~~ Review fixes: 83.7% on built-in songs, 89.6% on a black-key set with textbook fingering.
- Chord names come from all notes of a bar: a melody with few notes can get no name or a wrong name.
- No way to delete an imported song in the app yet (IDEAS.md). Remove the files in `~/Library/Application Support/Riyaz/songs/`.
- Fake-player runs one after the other within about 2 s: the app did not see the new port with the same name (hot-plug). A 5-second pause fixed it. Check with the real cable (IDEAS.md).
- The real file picker (`<input type="file">` in the pywebview window) is not clicked by the check script (it uploads a `File` object from JS). Test it by hand.

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
