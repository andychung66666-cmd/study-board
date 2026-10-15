from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Seg:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptResult:
    segments: list[Seg]
    duration_s: float
    language: str | None = None


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language: str, word_list: str) -> TranscriptResult: ...
