from typing import Literal, Optional
from pydantic import BaseModel, Field
Hand = Literal["left", "right", "unknown"]

class NoteNew(BaseModel):
    pitch: int = Field(ge=21, le=108); start: float = Field(ge=0); end: float
    velocity: int = Field(80, ge=1, le=127); hand: Hand = "unknown"

class NotePatch(BaseModel):
    pitch: Optional[int] = Field(None, ge=21, le=108); start: Optional[float] = Field(None, ge=0)
    end: Optional[float] = None; hand: Optional[Hand] = None
    suggested_finger: Optional[int] = Field(None, ge=1, le=5)
