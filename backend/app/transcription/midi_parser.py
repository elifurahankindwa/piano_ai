import pretty_midi, soundfile as sf
from .base import RawNote, Transcriber

class MidiParser(Transcriber):
    name = "midi-parse"
    def transcribe(self, path):
        pm = pretty_midi.PrettyMIDI(path)
        return [RawNote(n.start, n.end, n.pitch, n.velocity, None) for i in pm.instruments if not i.is_drum for n in i.notes]

def synthesize_preview(src, dst):
    """Plain synthesized WAV so MIDI projects have an audio clock for playback."""
    sf.write(dst, pretty_midi.PrettyMIDI(src).synthesize(fs=22050), 22050)
