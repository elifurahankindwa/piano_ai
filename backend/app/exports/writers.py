import csv, io, json
import pretty_midi
from app.db.store import meta

def to_json(p): return json.dumps({"project": meta(p), "notes": p["notes"], "chords": p["chords"]})

def to_csv(p):
    b = io.StringIO(); w = csv.writer(b); keys = ("id", "note_name", "pitch", "start", "end", "velocity", "confidence", "hand")
    w.writerow(keys); [w.writerow([n[k] for k in keys]) for n in p["notes"]]; return b.getvalue()

def to_midi(p):
    pm = pretty_midi.PrettyMIDI()
    for h in ("right", "left", "unknown"):
        ins = pretty_midi.Instrument(0, name=f"Estimated {h} hand")
        ins.notes = [pretty_midi.Note(n["velocity"], n["pitch"], n["start"], n["end"]) for n in p["notes"] if n["hand"] == h]
        if ins.notes: pm.instruments.append(ins)
    buf = io.BytesIO(); pm.write(buf); return buf.getvalue()
