# Talk Summary: implementation plan

Spec: `docs/superpowers/specs/2026-10-15-talk-summary-design.md` (approved 2026-10-15).
Status: draft, awaiting owner review and choice of execution method.

## Ground rules

- **Test-first** for every task (`mattpocock-skills:tdd`): write the failing test, see it fail, write the minimum code, see it pass, commit.
- **Fakes at the seams.** `Transcriber` and `Summariser` are protocols. Tests use fakes, so everything except the real Whisper, real Ollama, real microphone and real Meet-tab capture runs on any machine, including the cloud session.
- **Marking.** `[any]` = runs and is verified anywhere (Linux cloud or Mac). `[mac]` = needs the owner's Mac (Apple chip, Whisper model, Ollama, Chrome with real audio).
- **Python version.** The Mac ships Python 3.9. The project targets **Python 3.12**, installed with Homebrew in Task 0. Code must not rely on anything older than 3.12.
- **Layout.** All app code under `app/`, tests under `app/tests/`.
- **Branches.** One branch per milestone, named `build/m1-recorder` and so on, branched from `main` after the previous milestone is merged. One small commit per task. No pull request is opened unless the owner asks.
- **Review gate.** Before a milestone is merged: `code-review` and `security-review` skills, with findings fixed.

## File map

```
app/
  pyproject.toml            deps and pytest config
  run.sh                    one-command start
  talkboard/
    config.py               settings (models, data dir, port); Claude key from env only
    db.py                   SQLite schema, talk/segment/summary helpers, statuses
    storage.py              chunk append, finalise, delete files
    jobs.py                 single-worker queue, requeue on startup
    transcribe.py           Transcriber protocol, MlxWhisperTranscriber, prompt builder, OpenCC pass
    summarise/
      __init__.py           Summariser protocol, map-reduce pipeline, schema check
      split.py              timestamped segments -> ~10 minute pieces
      quotes.py             verbatim quote verification
      ollama.py             local LLM adapter
      claude.py             Claude API adapter
    search.py               FTS5 trigram + LIKE fallback
    server.py               FastAPI routes, startup checks
    static/                 index.html, recorder.js, library.js, style.css
  tests/
```

## Milestone 1: recorder and chunk saving

### Task 0: owner machine setup `[mac]`
Done by the owner, with a generated step-by-step script (`mattpocock-skills:wizard`). Nothing here can be done from the cloud.
1. `brew install python@3.12`.
2. Install Ollama; pull one starter model (final model chosen in Task 14).
3. `git clone`/`git pull` the repo; no virtual environment is needed until `run.sh` creates one.
Done when: `python3.12 --version` prints 3.12.x and `ollama list` runs.

### Task 1: skeleton, config, health route `[any]`
- Files: `app/pyproject.toml`, `app/talkboard/config.py`, `app/talkboard/server.py`, `app/tests/test_health.py`.
- Test first: `GET /api/health` returns 200 and `{"ok": true}`; config reads defaults (`whisper_model="mlx-community/whisper-large-v3-turbo"`, `host="127.0.0.1"`, `port=8765`) and never reads the Claude key from a file.
- Run: `cd app && python -m pytest -q`.
- Commit: "Add app skeleton, config and health route".

### Task 2: database and talk records `[any]`
- File: `app/talkboard/db.py`, test `app/tests/test_db.py`.
- Tables per spec 3.5: `talks`, `segments`, `summaries`. Statuses: `recording, recorded, transcribing, summarising, done, failed`.
- Tests first: create talk; legal and illegal status transitions (illegal raises); segments stored in order; deleting a talk cascades to segments and summaries.
- Commit: "Add SQLite schema and talk helpers".

### Task 3: chunk upload and storage `[any]`
- Files: `app/talkboard/storage.py`, routes in `server.py`, test `app/tests/test_chunks.py`.
- Routes: `POST /api/talks` (create, returns id), `PUT /api/talks/{id}/chunks/{n}` (append chunk n), `POST /api/talks/{id}/stop`.
- Tests first: chunks 0..N concatenate byte-exactly into `data/talks/<id>/audio.webm`; re-uploading an already stored chunk index is ignored; a gap (chunk 5 before chunk 4) is rejected with 409; stop on a talk with no chunks fails; stop sets status `recorded`.
- Commit: "Add chunk upload and stop".

### Task 4: recorder page `[any]` for the logic, `[mac]` for real audio
- Files: `static/index.html`, `static/recorder.js`; test `app/tests/e2e/test_recorder_smoke.py`.
- Features per spec 3.1: source choice (mic or tab), language, title, word list; `MediaRecorder` with 10 second timeslice and upload retry; level meter; near-silence warning after 10 seconds; screen wake lock; recording indicator and timer; Start blocked if the tab share has no audio track.
- Test first: Playwright with Chrome fake media flags (`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream`): start, wait for 3 chunks, stop, the talk exists with status `recorded` and a non-empty file.
- Mac check: record 2 minutes of real mic and 2 minutes of a Meet tab; both files play back.
- Commit: "Add recorder page".

**Milestone 1 done when** the Mac shows a recorded talk file for both sources.

## Milestone 2: transcription

### Task 5: job queue and recovery `[any]`
- File: `app/talkboard/jobs.py`, test `app/tests/test_jobs.py`.
- Tests first (with a fake transcriber): a stopped talk moves `recorded -> transcribing -> summarising`; two talks run one after the other, never together; on startup, talks left in `transcribing` or `summarising` are re-queued; a talk stuck in `recording` is only finalised by `POST /api/talks/{id}/recover`; a failing job sets `failed` with the error text; `POST .../retry` re-queues.
- Commit: "Add job queue with recovery".

### Task 6: transcriber `[any]` for logic, `[mac]` for real Whisper
- File: `app/talkboard/transcribe.py`, tests `app/tests/test_transcribe.py`.
- Tests first: prompt builder combines the Traditional-Chinese nudge and the talk's word list, and omits the nudge for `en`; OpenCC pass turns `极客` into `極客` and leaves English untouched; `MlxWhisperTranscriber` maps result segments to `(start, end, text)`.
- `[mac]` integration test, marked `@pytest.mark.mac`: transcribe a 10 second sample; skipped elsewhere.
- Commit: "Add Whisper transcriber".

### Task 7: library list and talk page `[any]`
- Files: `static/library.js`, routes `GET /api/talks`, `GET /api/talks/{id}`.
- Tests first: list returns newest first with status and duration; detail returns segments and audio URL; audio is served with range support so the player can seek; status polling updates the page (Playwright).
- Commit: "Add library and transcript view".

**Milestone 2 done when** a real 8 minute clip on the Mac produces a transcript in the library.

## Milestone 3: summary

### Task 8: summariser `[any]` for logic, `[mac]` for real Ollama
- Files: `summarise/split.py`, `quotes.py`, `ollama.py`, `__init__.py`; tests alongside.
- Tests first: splitting never cuts mid-segment and keeps each piece near 10 minutes; a transcript shorter than one piece skips the map step; quote check accepts a verbatim line (ignoring spacing and punctuation) and drops a made-up one; invalid JSON from the model gets exactly one retry and then fails cleanly; Ollama down raises a typed error the job layer turns into a retryable failure.
- Output schema per spec 3.3.
- Commit: "Add map-reduce summariser".

### Task 9: summary view `[any]`
- Summary shown above the transcript; "Retry summary" button on failure; quotes link to their timestamp in the audio player.
- Commit: "Show summaries in the talk page".

**Milestone 3 done when** a real talk shows a one-screen summary on the Mac and every quote is verbatim.

## Milestone 4: search, housekeeping, Claude button

### Task 10: search `[any]`
- File: `app/talkboard/search.py`, test `app/tests/test_search.py`.
- At startup, create the FTS5 `trigram` index; if the SQLite build lacks it, fall back to `LIKE` for every query and log a warning.
- Tests first: a 4 character Chinese phrase matches by FTS; a **2 character** Chinese word matches by the `LIKE` fallback; English search is case-insensitive; results come back with a short highlighted snippet.
- Commit: "Add transcript and summary search".

### Task 11: rename and delete `[any]`
- Tests first: rename updates title only; delete removes audio file, segments, summaries and index rows; deleting a talk that is currently processing is refused.
- Commit: "Add rename and delete".

### Task 12: Claude re-summarise `[any]` with a fake client, `[mac]` for one real call
- File: `summarise/claude.py`. Use the `claude-api` skill for the SDK call and model name.
- Tests first: no `ANTHROPIC_API_KEY` returns a clear message and changes nothing; with a fake client, the result is stored as `engine=claude` beside the local summary and the local one is untouched; API errors are shown and nothing is overwritten.
- Commit: "Add optional Claude re-summarise".

## Milestone 5: finish

### Task 13: startup checks, `run.sh`, README `[any]`
- `run.sh` creates the virtual environment with Python 3.12 on first run, installs dependencies, starts the server, prints `http://127.0.0.1:8765`.
- Startup checks per spec 3.6: `ffmpeg` present (hard fail with message), Ollama reachable (warning only), data directory writable.
- Test first: each check reports correctly when its dependency is faked as missing.
- Commit: "Add run script and startup checks".

### Task 14: acceptance and measurements `[mac]`
Owner runs the spec section 6 checks, and these measurements decide the open items:
1. Cantonese test (`spike/transcribe.py --language yue`): sets the default Whisper model.
2. Check of the wrong-looking words at 00:00-00:48 of the Mandarin clip.
3. Benchmark two or three 14B-class models in Ollama against Claude's summary on two talks; set the default.
4. Time a 60-90 minute transcription on the MacBook Air and watch for throttling.
5. Leave the recorder tab in the background for an hour; confirm chunks keep arriving.
6. Mute the Meet tab while recording; confirm whether the capture goes silent.
Results are written back into the spec's Open items.

### Task 15: interface polish and final review `[any]`
- `frontend-design` skill on the recorder and library pages; keep all functionality and tests green.
- Full `code-review` and `security-review` of the whole app. The server binds to `127.0.0.1` only; confirm no route is reachable from another machine and that the API key never appears in logs, files or responses.
- Commit: "Polish interface".

## Risks carried from the spec

Cantonese accuracy (Task 14.1) is the main one: if poor, add a paid engine behind the same `Transcriber` interface; only `transcribe.py` and config change. Local summary quality (Task 14.3) is the second: the Claude button already covers it.

## Execution choices

1. **Build in the cloud, test on the Mac (recommended).** Claude builds each milestone here with tests and fakes, pushes the branch, and the owner runs `git pull` and `./run.sh` on the Mac for the `[mac]` checks. Least Terminal work for the owner.
2. **Build on the Mac.** Claude Code runs locally on the Mac, so real Whisper and Ollama are available during development. More setup for the owner first.
3. **Mixed.** Cloud for `[any]` tasks, Mac sessions only for Tasks 4 (real audio), 6, 8, 12 and 14.
