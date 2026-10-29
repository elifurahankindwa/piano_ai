from fastapi import APIRouter, HTTPException
from app.db import store
from app.schemas.notes import NoteNew, NotePatch
from app.services.notes import commit, ensure_analysis, make_note
from app.music_analysis.theory import note_name

router = APIRouter(prefix="/api/v1/projects/{pid}/notes", tags=["notes"])

@router.get("")
def list_notes(pid: str, start: float = 0, end: float = 1e9, min_confidence: float = 0):
    return [n for n in store.load(pid)["notes"] if n["end"] >= start and n["start"] <= end and (n["confidence"] or 1) >= min_confidence]

@router.post("", status_code=201)
def add(pid: str, b: NoteNew):
    p = store.load(pid)
    if b.end <= b.start: raise HTTPException(422, "end must be after start")
    n = make_note(max([x["id"] for x in p["notes"]], default=-1) + 1, b.start, b.end, b.pitch, b.velocity, None, b.hand)
    n["user_edited"] = True; p["notes"].append(n); commit(p); return n

@router.patch("/{nid}")
def patch(pid: str, nid: int, b: NotePatch):
    p = store.load(pid); n = next((x for x in p["notes"] if x["id"] == nid), None)
    if not n: raise HTTPException(404, "No such note")
    n.update(b.model_dump(exclude_none=True)); n["note_name"] = note_name(n["pitch"]); n["user_edited"] = True
    if n["end"] <= n["start"]: raise HTTPException(422, "end must be after start")
    commit(p); return n

@router.delete("/{nid}", status_code=204)
def remove(pid: str, nid: int):
    p = store.load(pid); p["notes"] = [x for x in p["notes"] if x["id"] != nid]; commit(p)
