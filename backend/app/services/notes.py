from app.db import store
from app.music_analysis import chords as C
from app.music_analysis import key as K
from app.music_analysis.hands import estimate_hand
from app.music_analysis.theory import note_name

def make_note(i, start, end, pitch, velocity, confidence, hand=None):
    return {"id": i, "pitch": pitch, "note_name": note_name(pitch), "start": round(start, 4), "end": round(end, 4),
            "velocity": velocity, "confidence": confidence, "hand": hand or estimate_hand(pitch),
            "suggested_finger": None, "user_edited": False}

def commit(p):
    """Recompute everything derived from the notes, then persist."""
    p["chords"] = C.detect_chords(p["notes"])
    p["key"] = K.detect_key(p["notes"])
    store.save(p)

def ensure_analysis(p):
    """Recompute stored chords/key when they predate the current output format.

    Chords and key are cached in the project file, so projects created before a
    change to either detector would otherwise keep serving stale output until
    the next note edit. Both are symbolic and cost milliseconds, so doing this
    lazily on load is cheap.
    """
    if C.is_stale(p.get("chords")) or K.is_stale(p.get("key")):
        commit(p)
    return p
