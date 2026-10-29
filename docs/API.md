# API (also live at /docs)
| Method | Path | Purpose |
|---|---|---|
| POST | /api/v1/projects | Upload WAV/MP3/FLAC/MIDI (multipart `file`); returns `project_id`, starts analysis job |
| GET | /api/v1/projects/{id} | Metadata + job status (`queued`/`transcribing`/`completed`/`failed`), stage, progress |
| GET | /api/v1/projects/{id}/audio | Source audio (synthesized preview for MIDI) |
| GET | /api/v1/projects/{id}/notes | Notes; filters `start`, `end`, `min_confidence` |
| POST/PATCH/DELETE | /api/v1/projects/{id}/notes[/{nid}] | Add / edit / delete note (recomputes chords) |
| GET | /api/v1/projects/{id}/chords | Chord events (estimate). Fields: `symbol`, `root`, `quality`, `inversion`, `bass`, `confidence`, `note_ids`. Recomputed automatically if stored with an older format. |
| GET | /api/v1/projects/{id}/key | Estimated key (estimate). Fields: `name`, `tonic`, `minor`, `confidence`, `runner_up`, `margin`, `ambiguous`, `reason`, `chord_reliability`, `chords_used`, `harmony_share`, optional `relative_minor`/`relative_major`. Also returned in the project metadata. Recomputes automatically if stored with an older format. |
| GET, POST | /api/v1/projects/{id}/export/{json,csv,midi} | Downloads |
| GET | /api/v1/projects/{id}/export/video/presets | Video export options: resolutions (720p–4K, 24–60 fps), quality tiers (CRF), codecs (H.264/H.265/VP9), and whether ffmpeg is available |
| POST | /api/v1/projects/{id}/export/video | Starts a video render. Query: `resolution` (`1080p30`…), `quality` (`standard`/`high`/`maximum`), `codec` (`h264`/`h265`/`vp9`), `fps` (optional override), `start`/`end` (optional range in seconds). Returns the chosen options and a `job` id; renders in the background. If a render is already running the running one is returned instead (with `attached: true` and a `note`) rather than an error |
| GET | /api/v1/projects/{id}/export/video | Render status: `idle`/`queued`/`rendering`/`done`/`failed`, `progress`, `eta_seconds`, the `job` id that produced it, and on success `name`/`bytes`/`file` |
| GET | /api/v1/projects/{id}/export/video/file | Downloads the rendered video (MP4 or WebM). Always serves the last finished render, including while a newer one is running or after it failed |
| DELETE | /api/v1/projects/{id} | Delete project and files |
| GET | /api/health | Health check |
