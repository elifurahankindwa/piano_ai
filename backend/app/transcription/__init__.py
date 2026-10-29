from app.core.config import MIDI_EXT
from .base import Transcriber
from .basic_pitch_engine import BasicPitchTranscriber
from .midi_parser import MidiParser

def get_transcriber(ext: str) -> Transcriber:
    return MidiParser() if ext in MIDI_EXT else BasicPitchTranscriber()
