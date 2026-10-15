# Talk Summary: design spec

Date: 2026-10-15
Status: draft, awaiting owner review

## 1. Goal

A personal web app that records a talk and, when the talk ends, gives the owner a summary of the speaker's main points. The owner works on other things during the talk and reads the summary afterwards. Every talk is kept in a searchable library with its summary, transcript and audio.

**User:** one person (the owner), on their own MacBook (Apple Silicon, 24 GB).
**Success:** within a few minutes of pressing Stop on a 60-90 minute talk, the owner has a one-screen summary accurate enough that they would not feel they missed the talk.

### Non-goals (v1)

Live captions, speaker identification, multiple users, sharing or publishing, mobile or phone recording, desktop meeting apps (Zoom/Teams app), calendar integration, any hosting outside the owner's Mac.

## 2. Decisions

| Topic | Decision |
|---|---|
| Where it runs | Owner's Mac only. Server bound to `127.0.0.1`. No login. Started with one command, used in Chrome. |
| Audio sources | Laptop microphone, or one Chrome tab's audio (Google Meet, Zoom in the browser, YouTube Live). Chosen per talk. |
| Languages | Cantonese, Mandarin, English, and mixed. The owner picks the language when starting a talk, with an "auto" option. |
| Written script | Chinese transcripts are Traditional. Summaries are always English; Chinese names and terms stay where they matter. |
| Transcription | Local Whisper (`mlx-whisper`), run after Stop, not during the talk. Model is a setting; default `large-v3-turbo`. |
| Summary | Local LLM through Ollama by default. A "Re-summarise with Claude" button calls the Claude API, only when pressed. |
| Retention | Keep audio, transcript and summary for every talk, with a delete button per talk. |
| Consent | All talks are public and permitted to record. No consent flow in v1. |
| Cost | About zero. The only paid action is the optional Claude button (cents per talk). |

Evidence behind the transcription choice is in `spike/`: on a 7.8 minute Mandarin clip, `large-v3` ran at a real-time factor of 0.15 on the owner's MacBook Air. Sentences came through well; errors were brand names and sound-alike words. Cantonese and mixed-language accuracy are not yet tested (see Open items).

## 3. Architecture

One local Python process (FastAPI) serves a small web page, stores data in SQLite plus files on disk, and runs background jobs. The page is plain HTML and JavaScript with no build step. Whisper and the LLM sit behind two small interfaces (`Transcriber`, `Summariser`) so everything else can be tested with fakes.

```
Chrome page ──(audio chunks every 10 s)──▶ server ──▶ data/talks/<id>/audio.webm
     │                                        │
     │  press Stop                            ▼
     └──────────────────────────────▶ job queue (one at a time)
                                              │
                          Transcriber (mlx-whisper) ──▶ segments in SQLite
                                              │
                          Summariser (Ollama, or Claude on demand) ──▶ summary in SQLite
                                              │
Chrome page ◀──── library, summary, transcript, search, audio player
```

### 3.1 Recorder (browser)

- Start screen: pick source (mic or tab audio), pick language, optional word list, title. Start button.
- Mic: `getUserMedia` with echo cancellation on. Tab audio: `getDisplayMedia` with the video track discarded. If no audio track is present (the "Share tab audio" box was not ticked), Start is blocked with a clear message.
- `MediaRecorder` with a 10 second timeslice. Each chunk is uploaded immediately and appended to one file on the server, so a crashed tab loses at most 10 seconds.
- A live level meter, plus a warning if the first 10 seconds are near-silent. The owner will not be watching, so a silent recording must be caught early.
- A screen wake lock is held while recording so the Mac does not sleep mid-talk.
- A visible "recording" indicator and an elapsed timer.
- Stop finalises the file and enqueues the talk for processing.

### 3.2 Transcriber

- Runs after Stop through a single-worker job queue.
- Calls `mlx_whisper` with the model from config, the chosen language (or auto detect), and an `initial_prompt` made of a Traditional-Chinese nudge plus the talk's word list (speaker, companies, jargon). The word list is the main defence against wrong names.
- Segments (start, end, text) are stored in SQLite.
- Chinese output is passed through OpenCC (`s2t`) to remove stray Simplified characters.
- Status is shown on the talk page ("transcribing, 3 min elapsed"). Whisper gives no progress, so elapsed time only.

### 3.3 Summariser

- Long transcripts use map-reduce: split into about 10 minute pieces, extract notes from each, then merge the notes into the final summary. This keeps small local models inside their context window.
- Output is structured: TL;DR (3 lines), 5-8 key points, 3-5 quotes with timestamps, things the owner could act on, open questions. English.
- Every quote must appear in the transcript (checked after normalising whitespace and punctuation). Quotes that fail the check are dropped, not shown.
- "Re-summarise with Claude" sends the whole transcript in one request using the same output structure. The API key is read from the `ANTHROPIC_API_KEY` environment variable. The button does nothing if the key is unset, and says so. The result is stored beside the local summary so the two can be compared.
- The Ollama model name and the Claude model name are config values.

### 3.4 Library

- List of talks: title, date, length, status. Click for the detail page: summary at the top, transcript with timestamps below, audio player (plays only on press).
- Search across transcripts and summaries with SQLite FTS5 using the `trigram` tokenizer, which matches Chinese without word segmentation. Queries shorter than 3 characters (common for Chinese words) fall back to a `LIKE` scan.
- Rename and delete. Delete removes the audio file, transcript and summaries.

### 3.5 Data model

- `talks`: id, title, created_at, source (mic or tab), language, word_list, status, duration_s, audio_path, error.
- `segments`: talk_id, start_s, end_s, text.
- `summaries`: talk_id, engine (local or claude), model, created_at, body (JSON).
- FTS index over segment text and summary text.

Talk statuses: `recording`, `recorded`, `transcribing`, `summarising`, `done`, `failed`.

### 3.6 Configuration and startup

- One config file for model names, Whisper model, data directory and port. The Claude key comes from the environment only, never the file.
- A single command starts the server and prints the local address.
- Startup checks: `ffmpeg` present, Ollama reachable (a warning only, since transcripts still work without it), data directory writable.

## 4. Failure handling

| Failure | Behaviour |
|---|---|
| Browser tab or Mac dies mid-talk | Chunks already saved. The talk stays `recording`; a "Recover" button finalises the file and processes it. |
| Server restarts during a job | Talks in `transcribing` or `summarising` are re-queued on startup. |
| Ollama not running | Transcript is kept, status `summarising` fails with a message, "Retry summary" button. |
| Whisper or ffmpeg error | Status `failed`, error shown, audio kept, "Retry" button. |
| Mic permission denied or tab audio not shared | Start blocked with instructions. |
| Near-silent input | Warning during the first 10 seconds. |
| Claude call fails | Local summary is untouched; error shown next to the button. |

## 5. Testing

- Test-first for the pipeline pieces: chunk assembly into one file, job queue and recovery, transcript splitting for map-reduce, quote verification, OpenCC pass, FTS search including 1-2 character Chinese queries. `Transcriber` and `Summariser` are replaced by fakes in these tests.
- A browser smoke test with Chrome's fake media device flags: start, record a few chunks, stop, see the talk appear in the library.
- Manual acceptance on real talks (section 6).

## 6. Acceptance checks

1. Record 10 minutes from the mic in a real room: audio file exists, transcript appears, summary appears.
2. Record 10 minutes of a Google Meet tab: same.
3. Kill the browser tab during a recording, press Recover: transcript covers everything up to the crash.
4. A 60-90 minute talk finishes transcription in under 20 minutes on the owner's MacBook Air.
5. Search finds a two-character Chinese word that appears in a transcript.
6. Every quote shown in a summary is a verbatim line from its transcript.
7. Deleting a talk removes its files and database rows.

## 7. Open items

- **Cantonese and mixed-language accuracy are untested.** Owner to run `spike/transcribe.py` on 2-3 minutes of real Cantonese with English words, using `--language yue`. The result sets the default Whisper model. If it is poor, the fallback is a paid transcription engine behind the same `Transcriber` interface.
- **The Mandarin clip's wrong-looking words** (00:00-00:48) have not been checked against the audio by the owner.
- **Local LLM choice.** The first implementation task is to pick and benchmark a 4-bit, roughly 14B-class instruct model that fits in 24 GB, comparing its summaries with Claude's on two real talks.
- **Thermal behaviour.** The MacBook Air has no fan. A 90 minute transcription is a long sustained load; measure it during acceptance check 4.
- **Chrome background-tab behaviour.** Verify that chunk uploads continue when the recorder tab is in the background for an hour.
- **Muting a captured tab.** Verify whether muting the Meet tab also silences the captured audio.

## 8. Build order

1. Server skeleton, recorder page, chunk upload and save, minimal library list.
2. Job queue and transcription, transcript view, Recover.
3. Summariser (local), summary view, quote check.
4. Search, rename, delete, Claude re-summarise button.
5. Interface polish.

Each step is test-first and independently usable.

## 9. Skills for the build

- `mattpocock-skills:tdd` for every step.
- `frontend-design` for the recorder and library interface.
- `mattpocock-skills:wizard` for one-off owner setup steps (Ollama, model download).
- `claude-api` for the re-summarise button.
- `run` and the Playwright-based `webapp-testing` skill (to be installed if wanted) for checking the real app.
- `code-review` and `security-review` before each merge.
