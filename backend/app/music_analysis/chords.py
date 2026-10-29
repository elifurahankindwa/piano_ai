"""Chord estimation from transcribed notes.

Purely symbolic: no model, no download, no audio. Runtime is ~0.1 s for a
multi-minute song, so it is safe to call on every note edit.

Two stages:
  1. `detect_chords` scores chord templates against the set of sounding pitch
     classes in each note-boundary window.
  2. `merge_chords` cleans up the raw output. Note-by-note windowing produces
     very short, flickering chords (a held chord re-articulated as separate
     notes splits into many fragments); we merge adjacent identical chords
     across short gaps and fold away pairs too short to read.

Everything here is an *estimate* and is labelled as such in the UI.
"""
from .theory import NAMES

# Bump when the shape or meaning of chord output changes, so projects stored
# with an older format can be recomputed on load instead of showing stale data.
CHORD_FORMAT = 2

# Root-position interval sets (semitones from the root). Ordered loosely from
# most to least common; ties are broken by the template score, not this order.
TEMPLATES = {
    "":     [0, 4, 7],
    "m":    [0, 3, 7],
    "7":    [0, 4, 7, 10],
    "m7":   [0, 3, 7, 10],
    "maj7": [0, 4, 7, 11],
    "dim":  [0, 3, 6],
    "aug":  [0, 4, 8],
    "sus2": [0, 2, 7],
    "sus4": [0, 5, 7],
    "dim7": [0, 3, 6, 9],
    "m7b5": [0, 3, 6, 10],
    "6":    [0, 4, 7, 9],
    "m6":   [0, 3, 7, 9],
    "9":    [0, 4, 7, 10, 14],
    "maj9": [0, 4, 7, 11, 14],
    "m9":   [0, 3, 7, 10, 14],
    "add9": [0, 4, 7, 14],
    "5":    [0, 7],
}

# Common triads/7ths get a small edge so the vocabulary additions do not
# steal unambiguous triads.
_PREFERRED = {"", "m", "7", "m7", "maj7"}

MIN_WINDOW = 0.08      # seconds; ignore windows shorter than this
MERGE_GAP = 0.25       # merge identical chords separated by less than this
MIN_CHORD = 0.12       # drop chords shorter than this


def _best(pcs, bass=None):
    """Score every (root, quality) template against a set of pitch classes.

    `bass` is the actual lowest sounding pitch class, used only to break ties
    toward a plausible root and to detect slash chords.
    """
    out = None
    for r in range(12):
        for q, iv in TEMPLATES.items():
            tp = {(r + i) % 12 for i in iv}
            # reward template tones present, penalise both kinds of mismatch
            s = len(pcs & tp) - .5 * len(pcs - tp) - .5 * len(tp - pcs)
            if q in _PREFERRED:
                s += .1
            # a template whose root is the bass note is more likely correct
            if bass is not None and r == bass:
                s += .2
            if out is None or s > out[0]:
                out = (s, r, q, iv, tp)
    return out


def _inversion(notes, root, iv):
    """Inversion index from the lowest sounding pitch, plus a slash bass.

    Returns (inversion, bass_pc, is_slash). `is_slash` is True when the lowest
    note is not a chord tone, which we surface as an explicit slash bass.
    """
    lowest = min(n["pitch"] for n in notes)
    bass = lowest % 12
    rel = (lowest - root) % 12
    if rel in iv:
        return iv.index(rel), bass, False
    return None, bass, True


def _is_power_chord(pcs):
    """True when exactly two pitch classes form a bare root+fifth (no third).

    Two-note windows are otherwise too ambiguous to name (C+E may be Cmaj or
    Am), so they stay unreported unless they are an unambiguous power chord.
    """
    if len(pcs) != 2:
        return False
    a, b = sorted(pcs)
    return (b - a) % 12 == 7 or (a - b) % 12 == 7


def detect_chords(notes):
    """Chord events from note dicts. Needs >=3 pitch classes, or a power chord."""
    ns = sorted(notes, key=lambda n: n["start"])
    pts = sorted({round(x, 3) for n in ns for x in (n["start"], n["end"])})
    act, i, out = [], 0, []
    for a, b in zip(pts, pts[1:]):
        while i < len(ns) and ns[i]["start"] <= a + 1e-6:
            act.append(ns[i]); i += 1
        act = [n for n in act if n["end"] > a + 1e-6]
        pcs = {n["pitch"] % 12 for n in act}
        if b - a < MIN_WINDOW:
            continue
        if len(pcs) < 3 and not _is_power_chord(pcs):
            continue
        bass = min(n["pitch"] for n in act) % 12
        s, r, q, iv, tp = _best(pcs, bass)
        inv, bass_pc, is_slash = _inversion(act, r, iv)
        symbol = NAMES[r] + q
        if is_slash:
            symbol += "/" + NAMES[bass_pc]
        c = {"start": a, "end": b, "symbol": symbol, "root": r, "quality": q,
             "inversion": inv, "bass": bass_pc, "chord_format": CHORD_FORMAT,
             "confidence": round(min(1, max(0, s) / len(tp)), 2),
             "note_ids": [n["id"] for n in act]}
        out.append(c)
    return merge_chords(out)


def is_stale(stored):
    """True when a project's stored chords predate the current output format."""
    if not stored:
        return True
    return stored[0].get("chord_format") != CHORD_FORMAT


def merge_chords(chords, gap=MERGE_GAP, min_dur=MIN_CHORD):
    """Collapse flicker: join identical chords across short gaps, drop slivers.

    The symbolic windowing emits a new event whenever any note starts or ends,
    so a sustained chord played as repeated notes becomes a run of fragments.
    Merging those is what makes the reading stable.
    """
    if not chords:
        return []
    merged = []
    for c in chords:
        p = merged[-1] if merged else None
        if p and p["symbol"] == c["symbol"] and c["start"] - p["end"] < gap:
            p["end"] = c["end"]
            p["confidence"] = max(p["confidence"], c["confidence"])
            p["note_ids"] = sorted(set(p["note_ids"]) | set(c["note_ids"]))
            if p.get("inversion") is None and c.get("inversion") is not None:
                p["inversion"] = c["inversion"]; p["bass"] = c["bass"]
        else:
            merged.append(dict(c))
    # Drop anything still too short to read, then re-merge in case removal
    # brought two identical neighbours together.
    kept = [c for c in merged if c["end"] - c["start"] >= min_dur]
    if len(kept) != len(merged):
        out = []
        for c in kept:
            p = out[-1] if out else None
            if p and p["symbol"] == c["symbol"] and c["start"] - p["end"] < gap:
                p["end"] = c["end"]
                p["note_ids"] = sorted(set(p["note_ids"]) | set(c["note_ids"]))
                p["confidence"] = max(p["confidence"], c["confidence"])
            else:
                out.append(c)
        return out
    return kept
