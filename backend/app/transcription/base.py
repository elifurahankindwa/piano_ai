from abc import ABC, abstractmethod
from typing import NamedTuple, Optional

class RawNote(NamedTuple):
    start: float; end: float; pitch: int; velocity: int; confidence: Optional[float]

class Transcriber(ABC):
    """Replaceable engine interface: file path in, note events out. Never fabricate output."""
    name: str
    @abstractmethod
    def transcribe(self, path: str) -> list[RawNote]: ...
