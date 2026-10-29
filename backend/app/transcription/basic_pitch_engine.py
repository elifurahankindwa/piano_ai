from .base import RawNote, Transcriber

class BasicPitchTranscriber(Transcriber):
    name = "basic-pitch"
    def transcribe(self, path):
        try: from basic_pitch.inference import predict
        except ImportError: raise RuntimeError("Transcription model missing. Run: pip install basic-pitch")
        _, _, events = predict(path)
        return [RawNote(s, e, int(p), int(min(127, 127 * a)), round(float(a), 3)) for s, e, p, a, _ in events if 21 <= p <= 108]
