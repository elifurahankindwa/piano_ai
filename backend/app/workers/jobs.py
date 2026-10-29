import json
from app.core.config import MIDI_EXT, settings
from app.db import store
from app.services.notes import commit, make_note
from app.transcription import get_transcriber
from app.transcription.midi_parser import synthesize_preview

def run_job(pid):
    p = store.load(pid)
    def st(**k): p.update(k); store.save(p)
    try:
        d = settings.data_dir / pid; src = str(d / ("source" + p["ext"]))
        tr = get_transcriber(p["ext"]); st(status="transcribing", stage=f"running {tr.name}", progress=.2)
        raw = sorted(tr.transcribe(src), key=lambda r: (r.start, r.pitch))
        if p["ext"] in MIDI_EXT:
            synthesize_preview(src, str(d / "audio.wav"))
            import soundfile as sf; p["duration"] = float(sf.info(str(d / "audio.wav")).duration)
        st(stage="post-processing", progress=.8)
        p["notes"] = [make_note(i, *r) for i, r in enumerate(raw)]
        p["orig_notes"] = json.loads(json.dumps(p["notes"])); p["model"] = tr.name
        commit(p); st(status="completed", stage="done", progress=1.0)
    except Exception as ex: st(status="failed", stage="error", error=str(ex))
