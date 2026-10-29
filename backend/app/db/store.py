"""File-backed project store (one JSON per project). Swap for SQL later behind these functions."""
import json, shutil, threading, uuid
from fastapi import HTTPException
from app.core.config import settings

_LOCK = threading.Lock()

def project_dir(pid):
    try: uuid.UUID(pid)  # rejects path traversal
    except ValueError: raise HTTPException(404, "Unknown project")
    d = settings.data_dir / pid
    if not d.exists(): raise HTTPException(404, "Unknown project")
    return d

def load(pid): return json.loads((project_dir(pid) / "project.json").read_text())

def save(p):
    with _LOCK: (settings.data_dir / p["id"] / "project.json").write_text(json.dumps(p))

def new_dir():
    pid = uuid.uuid4().hex; (settings.data_dir / pid).mkdir(); return pid

def remove(pid): shutil.rmtree(project_dir(pid))

def meta(p): return {k: v for k, v in p.items() if k not in ("notes", "orig_notes", "chords")} | {"note_count": len(p["notes"])}
