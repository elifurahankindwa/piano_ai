import shutil, time
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from app.core.config import AUDIO_EXT, MIDI_EXT, settings
from app.db import store
from app.services.notes import ensure_analysis
from app.workers.jobs import run_job

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])

@router.post("", status_code=202)
async def create(bg: BackgroundTasks, file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT | MIDI_EXT: raise HTTPException(415, f"Unsupported type {ext}. Use WAV, MP3, FLAC or MIDI.")
    pid = store.new_dir(); d = settings.data_dir / pid; src = d / ("source" + ext); size = 0
    def fail(code, msg): shutil.rmtree(d, ignore_errors=True); raise HTTPException(code, msg)
    with open(src, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > settings.max_mb << 20: break
            out.write(chunk)
    if size > settings.max_mb << 20: fail(413, f"Max {settings.max_mb} MB")
    dur = None
    if ext in AUDIO_EXT:
        try:
            import librosa; dur = float(librosa.get_duration(path=str(src)))
        except Exception: fail(422, "File is corrupted or cannot be decoded")
        if not .1 <= dur <= settings.max_sec:
            fail(422, f"Duration must be 0.1s-{settings.max_min:g}min (got {dur/60:.1f}min)")
    p = {"id": pid, "name": Path(file.filename).stem[:80], "filename": Path(file.filename).name[:120], "ext": ext, "duration": dur,
         "status": "queued", "stage": "queued", "progress": 0, "error": None, "created": time.time(), "model": None,
         "notes": [], "orig_notes": [], "chords": [], "key": None}
    store.save(p); bg.add_task(run_job, pid)
    return {"project_id": pid, "status": "queued"}

@router.get("/{pid}")
def get(pid: str): return store.meta(store.load(pid))

@router.get("/{pid}/audio")
def audio(pid: str):
    d = store.project_dir(pid); p = store.load(pid)
    f = d / ("source" + p["ext"]) if p["ext"] in AUDIO_EXT else d / "audio.wav"
    if not f.exists(): raise HTTPException(404, "No audio yet")
    return FileResponse(f)

@router.get("/{pid}/chords")
def chords(pid: str): return ensure_analysis(store.load(pid))["chords"]

@router.get("/{pid}/key")
def key(pid: str):
    """Estimated key of the project (harmonic + key-profile analysis). Estimate only."""
    ensure_analysis(store.load(pid))
    return store.load(pid).get("key")

@router.delete("/{pid}", status_code=204)
def delete(pid: str): store.remove(pid)
