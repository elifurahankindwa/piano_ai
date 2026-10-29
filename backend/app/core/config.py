import os
from pathlib import Path

AUDIO_EXT = {".wav", ".mp3", ".flac"}
MIDI_EXT = {".mid", ".midi"}

class Settings:
    data_dir = Path(os.getenv("DATA_DIR", "data"))
    # Upload limits. A 25-minute song is ~23 MB as 128 kbps MP3 but ~252 MB as
    # stereo WAV, so the size cap has to be generous enough for lossless audio.
    max_mb = int(os.getenv("MAX_MB", 400))
    max_min = float(os.getenv("MAX_MIN", 25))
    max_sec = max_min * 60
    # Video export renders every frame on the CPU, so the cost scales with
    # length x frame rate x pixels. Cap the length of a single render; longer
    # material can be exported in sections.
    video_max_min = float(os.getenv("VIDEO_MAX_MIN", 10))
    frontend_dir = Path(os.getenv("FRONTEND_DIR", Path(__file__).resolve().parents[3] / "frontend"))

settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
