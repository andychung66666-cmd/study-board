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


# Whisper has no "write Traditional characters" switch. A prompt written in the
# wanted script and register is the usual way to steer it.
NUDGES = {
    "yue": "以下係廣東話內容，可能夾雜English。請用繁體中文。",
    "zh": "以下是普通話內容，可能夾雜English。請使用繁體中文。",
    "auto": "以下內容可能係廣東話、普通話或English，請用繁體中文。",
}
CHINESE_LANGUAGES = ("zh", "yue", "auto")

_converter = None


def build_prompt(language: str, word_list: str) -> str:
    parts = []
    if language in NUDGES:
        parts.append(NUDGES[language])
    words = word_list.strip()
    if words:
        parts.append(("Names and terms: " if language == "en" else "相關名詞：") + words)
    return " ".join(parts)


def to_traditional(text: str, language: str) -> str:
    """Turns stray Simplified characters into Traditional; English talks are untouched."""
    global _converter
    if language not in CHINESE_LANGUAGES:
        return text
    if _converter is None:
        from opencc import OpenCC

        _converter = OpenCC("s2t")
    return _converter.convert(text)


class MlxWhisperTranscriber:
    """Local Whisper on Apple Silicon through mlx-whisper (installed with the 'mac' extra)."""

    def __init__(self, model: str, transcribe_fn=None):
        self.model = model
        self._transcribe_fn = transcribe_fn

    def _fn(self):
        if self._transcribe_fn is None:
            import mlx_whisper

            self._transcribe_fn = mlx_whisper.transcribe
        return self._transcribe_fn

    def transcribe(self, audio_path: Path, language: str, word_list: str) -> TranscriptResult:
        raw = self._fn()(
            str(audio_path),
            path_or_hf_repo=self.model,
            language=None if language == "auto" else language,
            initial_prompt=build_prompt(language, word_list) or None,
            verbose=False,
        )
        segments = [
            Seg(s["start"], s["end"], to_traditional(s["text"].strip(), language))
            for s in raw.get("segments", [])
        ]
        duration = segments[-1].end if segments else 0.0
        return TranscriptResult(segments, duration, raw.get("language"))
