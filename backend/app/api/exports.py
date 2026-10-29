from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from fastapi.responses import FileResponse
from pathlib import Path
from app.core.config import settings
from app.db import store
from app.exports import video as V
from app.exports import writers
from app.workers import video_jobs

router = APIRouter(prefix="/api/v1/projects/{pid}/export", tags=["export"])
def _dl(body, mime, pid, ext): return Response(body, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{pid}.{ext}"'})

@router.get("/json")
def j(pid: str): return _dl(writers.to_json(store.load(pid)), "application/json", pid, "json")
@router.get("/csv")
def c(pid: str): return _dl(writers.to_csv(store.load(pid)), "text/csv", pid, "csv")
@router.post("/midi")
def m(pid: str): return _dl(writers.to_midi(store.load(pid)), "audio/midi", pid, "mid")

# --- Video export -------------------------------------------------------------
# Rendering is a long job, so it runs in the background: POST starts it, GET polls
# the progress, and /video/file downloads the result.

@router.get("/video/presets")
def video_presets(): return V.presets()

@router.post("/video")
def start_video(pid: str, bg: BackgroundTasks, resolution: str = "1080p30", quality: str = "high",
                codec: str = "h264", fps: int | None = None, start: float = 0, end: float | None = None):
    p = store.load(pid)
    exe, _ = V.ffmpeg_bin()
    if not exe:
        raise HTTPException(503, "ffmpeg is not available. Install it system-wide, or run: pip install imageio-ffmpeg")
    res = next((r for r in V.RESOLUTIONS if r["id"] == resolution), None)
    if not res: raise HTTPException(400, f"Unknown resolution '{resolution}'")
    if quality not in V.CRF: raise HTTPException(400, f"Unknown quality '{quality}'")
    if codec not in ("h264", "h265", "vp9"): raise HTTPException(400, f"Unknown codec '{codec}'")
    if fps is not None and not 1 <= fps <= 120: raise HTTPException(400, "fps must be between 1 and 120")
    dur = V.audio_duration(store.project_dir(pid), p)
    if not dur: raise HTTPException(422, "This project has no audio to render")
    s = max(0.0, float(start))
    e = dur if end is None else min(float(end), dur)
    if e <= s: raise HTTPException(400, "The range end must be after the start")
    if (e - s) / 60 > settings.video_max_min:
        raise HTTPException(400, f"A single render is limited to {settings.video_max_min:g} minutes. Pick a shorter range.")

    cur = video_jobs.read_state(pid)
    if cur.get("status") in ("queued", "rendering"):
        # A render is already under way. Attach to it rather than refusing: the
        # caller gets the running job to watch, not an error to be confused by.
        return {**cur, "job": cur.get("job"), "attached": True,
                "note": "A render is already running - showing that one instead."}

    opts = {"resolution": resolution, "quality": quality, "codec": codec, "fps": int(fps or res["fps"]),
            "width": res["width"], "height": res["height"], "crf": V.CRF[quality][codec],
            "speed": V.SPEED[quality], "start": s, "end": e}
    job = video_jobs.new_job_id()
    video_jobs.start(pid, opts, job)  # publish "queued" before the worker picks it up
    bg.add_task(video_jobs.run_video_job, pid, opts, job)
    return {"status": "queued", "job": job, **opts}

@router.get("/video")
def video_status(pid: str):
    store.load(pid)  # 404 for an unknown project
    return video_jobs.read_state(pid)

@router.get("/video/file")
def video_file(pid: str):
    store.load(pid)  # 404 for an unknown project
    st = video_jobs.read_state(pid)
    if not st.get("file"): raise HTTPException(404, "No rendered video yet")
    path = Path(st["file"])
    if not path.exists(): raise HTTPException(404, "The rendered video is no longer on disk. Render it again.")
    mime = "video/webm" if path.suffix == ".webm" else "video/mp4"
    return FileResponse(path, media_type=mime, filename=st.get("name") or path.name)
