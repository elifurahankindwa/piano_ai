# Piano AI (MVP)

Audio/MIDI → note events → synchronized virtual keyboard + piano roll.

## Structure
```
piano-ai/
├── backend/
│   ├── app/
│   │   ├── api/             routers: projects, notes, exports
│   │   ├── core/            config / env settings
│   │   ├── db/              project store (JSON files; swap for SQL here)
│   │   ├── schemas/         Pydantic models
│   │   ├── services/        note creation, edit commit
│   │   ├── transcription/   Transcriber interface, Basic Pitch + MIDI parser
│   │   ├── music_analysis/  chords, hand heuristic, theory helpers
│   │   ├── fingering/       placeholder (not implemented)
│   │   ├── workers/         background analysis job
│   │   ├── exports/         JSON / CSV / MIDI / video writers
│   │   └── main.py
│   ├── tests/  requirements.txt
├── frontend/  index.html, src/styles.css, src/app.js
├── docs/API.md  sample_data/  scripts/
├── .env.example  .gitignore
```

## Run
```
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Basic Pitch's normal install fails on Python 3.12; this workaround was verified:
pip install --no-deps basic-pitch && pip install onnxruntime resampy mir_eval scipy
uvicorn app.main:app --reload     # http://localhost:8000, API docs at /docs
pytest                            # from backend/
```
To configure, copy `.env.example` to `.env` and export the variables (or set them inline).

## Upload limits
| Variable | Default | Notes |
|---|---|---|
| `MAX_MIN` | `25` | Maximum audio length in minutes. Files longer than this are rejected with a readable message. |
| `MAX_MB` | `400` | Maximum upload size. Needed because 25 min of audio is ~23 MB as 128 kbps MP3 but ~252 MB as stereo WAV, so a small cap would reject lossless audio well before the duration limit. |
| `DATA_DIR` | `data` | Where projects are stored. |
| `FRONTEND_DIR` | `../frontend` | Static frontend root. |
| `VIDEO_MAX_MIN` | `10` | Longest stretch of audio a single video render may cover. Longer material is exported in sections. |

Raising `MAX_MIN` alone is not enough — `MAX_MB` has to cover the format you upload. At 25 minutes:
MP3 128 kbps ≈ 23 MB, MP3 320 kbps ≈ 57 MB, stereo WAV 44.1 kHz ≈ 252 MB.

**25-minute songs are slow to transcribe on CPU-only hardware.** Basic Pitch inference is the bottleneck
(roughly single-digit multiples of realtime on a modest CPU), and a 25-minute song produces on the order of
17k notes. Analysis runs in a background task, and progress is reported through the project status endpoint,
so the page stays responsive while it works. Lower `MAX_MIN` if you want to keep jobs short.

| `key` | Estimated key (e.g. `"B major"`) shown in the side panel with a confidence and a warning when the match is weak. See "Key estimation" below. |

## Video export
The Export panel can render the piano roll to a video file with the audio muxed in.

**It is rendered on the server, not recorded in the browser.** A browser can only capture the canvas it is
drawing *right now*, in real time, using whatever codec the browser supports — so a browser export takes as
long as the song plays and its quality is capped by the browser's encoder. Rendering server-side runs as fast
as the CPU allows, always produces a file with an audio track, and exposes the knobs that actually decide
quality: resolution, frame rate and CRF.

Options (the sidebar panel, `GET /export/video/presets`):

| Option | Values | Notes |
|---|---|---|
| Resolution | 720p, 1080p, 1440p, 4K | 720p and 1080p come in 30 or 60 fps, 1440p is 60 fps, 4K in 30 or 60. |
| Quality | Standard / High / Maximum | Maps to a CRF per codec: H.264 23/18/16, H.265 30/26/22, VP9 32/24/18, and to an x264/x265 speed preset. |
| Codec | H.264 (MP4), H.265 (MP4), WebM (VP9) | H.264 plays everywhere; H.265 halves the size but needs a newer player; VP9 ships as WebM with Opus audio. |
| Range | Optional start/end in seconds | Export a section of a long recording. Capped by `VIDEO_MAX_MIN`. |

Rendering needs **ffmpeg**: a system install is used if one is on `PATH`, otherwise the binary bundled with
`imageio-ffmpeg` (already in `requirements.txt`) is used. Without either, the panel says so and the endpoint
answers `503` rather than failing halfway through.

Every frame is drawn with Pillow in the app's own colours (hand colours, faded low-confidence notes, the
falling-notes roll, the keyboard, the key and the current chord), and the frames are piped straight into
ffmpeg as raw RGB — no intermediate image files. The static parts of a frame (lanes, keyboard, title) are
drawn once and reused, which cut the per-frame cost roughly in half.

**Cost:** every frame is drawn and encoded on the CPU, so a render runs at a fraction of real time — roughly
0.3–0.5x at 1080p30 on a modest 4-core machine (a 4-minute song takes several minutes), and considerably
slower at 4K60. It runs as a background job with progress and a time estimate, so the page stays usable.

**Renders are safe to interrupt.** The encoder writes to a hidden temporary file and the finished video is
moved into place in one step, so a file that is being downloaded is always a complete video and never a
half-written one. Each render carries a job id, so the panel always reports the render it is actually
watching; clicking "Render video" again while one is running joins that render instead of failing. The
download keeps working while a new render is under way, and it still works if that render fails. If the
server is stopped mid-render the job dies with it, and the next request notices the render has gone stale
and lets a new one start rather than refusing forever.

## Verified
Backend tests (44 pass); real Basic Pitch transcription via the API (3-minute synthetic file end to end, 10 s);
upload boundary checks (24.99 min accepted, 25.10 min rejected, 252 MB stereo WAV accepted); frontend sync logic
(jsdom); chord estimation checked against known note sets and a real song; key estimation measured on 480
constructed excerpts across 12 roots x 2 modes x 4 textures (100% of the results it does not flag ambiguous were
correct; percussion and single-line material flagged rather than guessed at), plus three MIDI files uploaded
through the live API and confirmed in the correct key; stale chord/key migration exercised through the live API;
piano-roll rendering and click-to-select verified at real scale, including a synthetic 50k-note / 25-minute project
(notes land flush on the playhead line; the time-bucket index matched brute force exactly on both real projects and
ran ~40x faster per frame); video export exercised end to end through the live API and the browser — the panel
offers every resolution/quality/codec option, a render of a real song produces an MP4 that the browser decodes
(1280×720, correct duration, video + AAC audio streams) and whose frames match the drawn frames (note bars,
hand colours, white keys, playhead line), and notes land flush on the keyboard line exactly as in the live view.
The download path was checked as well: the file the browser saves decodes cleanly (4.00 s, H.264 + AAC), a
second click during a render joins the running job instead of erroring, and downloading *while* a new render
overwrites the same file still yields the complete previous video.
Not verified: real-browser audio playback, real piano recordings, key accuracy on real music (no labelled corpus
available), vocal detection (see below).

## Piano roll performance
The render loop only touches notes near the playhead, via a 1-second time-bucket index
(`indexNotes` / `notesIn` / `notesAt` in `frontend/src/app.js`). Without it, every animation frame scanned the
whole note list twice, which cost ~2.1 ms/frame at 17k–50k notes (about 13% of a 60 fps budget) and made long
songs stutter. Indexed lookups cost ~0.05 ms/frame (~0.3%), a ~40x reduction. The index is rebuilt whenever
notes are loaded or edited.

## Chord estimation
`music_analysis/chords.py` is purely symbolic — no model, no download, ~0.1 s per song. It merges note-level
windows into stable chord events (a held chord re-articulated as separate notes would otherwise split into many
fragments), names triads, 6ths, 7ths, 9ths, sus and 5 chords, uses the lowest sounding pitch for inversions, and
emits an explicit slash bass (`C/F#`) when the bass is not a chord tone. Two-note windows are only named when
they form an unambiguous power chord. All chord output is an **estimate**.

## Key estimation
`music_analysis/key.py` is also purely symbolic and costs a few milliseconds. Earlier versions used the plain
Krumhansl-Schmuckler key-profile correlation on the pitch-class histogram, and it was measurably inaccurate —
it confused minor keys with their relative majors. That is not a tuning problem: a natural minor scale and its
relative major contain the *same seven pitch classes*, so a histogram cannot separate them by construction.

The current version leads with **harmonic evidence**: the chord progression already computed by `chords.py`,
scored by functional scale degree (how much time sits on the tonic, dominant, subdominant…) and weighted toward
the first and last chords, since tonal music begins and ends on its tonic. Chord qualities decide the mode, which
is exactly what the histogram throws away — the tonic chord of C minor is C-Eb-G (minor) while the tonic chord of
Eb major is Eb-G-Bb (major). Temperley's bias-free key profiles (the original Krumhansl-Kessler weights sum to
~6.5% more for minor, a documented bias) are kept as a secondary signal for material the chord detector could not
read.

**Harmony is only as good as the chords it is given**, so the two signals are combined by how much the chords can
be trusted. Feeding the scorer *perfect* chords recovers the key 24/24, so the scoring logic is sound; failures
came from upstream. On overlapping or arpeggiated material the detector reads the right chord roots but reports
them as power chords (`C5`), which have no third and therefore state no mode — defaulting those to major made
every such minor key come back as its parallel major. Such chords are now treated as mode-neutral, and
`chord_reliability` measures how much of the progression is genuinely usable.

Measured on 480 constructed excerpts (12 roots × 2 modes × 5 seeds × 4 textures: dense, clean, arpeggiated,
single-line): **67.5% exact overall**. The more useful number is that among results the detector does *not* flag
ambiguous, accuracy is **100%** — it declines to answer on material it cannot read rather than guessing. These are
constructed excerpts; no labelled corpus of real recordings was available, so no accuracy claim is made about real
music.

**The label is an estimate, and the UI says so.** The result carries `confidence` (0..1), `runner_up`, `margin`,
`chord_reliability`, and an `ambiguous` flag with a `reason`. Percussion-only uploads (transcribed as stacks of
power chords) now score near-zero reliability and are flagged instead of being given a confident key; the panel
shows the warning rather than a confident-looking label. A near-tie result also names the competing key (usually
the relative minor/major) so the ambiguity is visible instead of hidden.

## Not implemented
React/TS/Tailwind, WebSockets, Celery/Redis, SQL database, auth, rate limits, source separation, fingering,
key/tempo analysis, undo/redo, evaluation script, live input.

### Vocal detection (evaluated, deliberately not shipped)
Vocal-activity detection was attempted with cheap DSP features (HPSS harmonic/band-energy ratio, and pyin pitch
salience) so it could run without a separation model. Tested against synthetic audio with **known** vocal and
instrumental regions, both approaches scored the instrumental sections as *more* vocal-like than the actual
vocal, i.e. they were inverted and would mislead. Rather than ship an unreliable labeler, the feature was dropped.
Reliable vocal detection needs a trained model (or a separation model such as Demucs, which is far too slow on
CPU-only hardware). Also note `librosa.pyin` cost ~2x realtime, so it was not even cheap.

