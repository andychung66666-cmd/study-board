import pytest

from talkboard.transcribe import (
    MlxWhisperTranscriber,
    Seg,
    build_prompt,
    to_traditional,
)


def test_cantonese_prompt_asks_for_traditional_characters_and_lists_the_words():
    prompt = build_prompt("yue", "OpenAI, 阿里巴巴")
    assert "廣東話" in prompt
    assert "繁體" in prompt
    assert "OpenAI, 阿里巴巴" in prompt


def test_mandarin_and_auto_prompts_also_ask_for_traditional_characters():
    assert "普通話" in build_prompt("zh", "")
    assert "繁體" in build_prompt("zh", "")
    assert "繁體" in build_prompt("auto", "")


def test_english_prompt_has_no_chinese_nudge_and_is_empty_without_a_word_list():
    assert build_prompt("en", "") == ""
    prompt = build_prompt("en", "Anthropic, Claude")
    assert "Anthropic, Claude" in prompt
    assert "繁體" not in prompt


def test_chinese_talks_are_converted_to_traditional():
    assert to_traditional("极客 AI 开发", "zh") == "極客 AI 開發"
    assert to_traditional("极客", "yue") == "極客"
    assert to_traditional("极客", "auto") == "極客"


def test_english_talks_are_left_alone():
    assert to_traditional("极客 stays", "en") == "极客 stays"


class FakeMlx:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, audio, **kwargs):
        self.calls.append((audio, kwargs))
        return self.result


RESULT = {
    "language": "zh",
    "segments": [
        {"start": 0.0, "end": 4.2, "text": " 极客来了 "},
        {"start": 4.2, "end": 9.7, "text": "Hello 世界"},
    ],
}


def test_result_segments_are_stripped_converted_and_timed(tmp_path):
    transcriber = MlxWhisperTranscriber("some/model", transcribe_fn=FakeMlx(RESULT))
    result = transcriber.transcribe(tmp_path / "a.webm", "zh", "")
    assert result.segments == [Seg(0.0, 4.2, "極客來了"), Seg(4.2, 9.7, "Hello 世界")]
    assert result.duration_s == 9.7
    assert result.language == "zh"


def test_whisper_is_called_with_model_language_and_prompt(tmp_path):
    fake = FakeMlx(RESULT)
    transcriber = MlxWhisperTranscriber("some/model", transcribe_fn=fake)
    audio = tmp_path / "a.webm"

    transcriber.transcribe(audio, "yue", "OpenAI")

    ((path, kwargs),) = fake.calls
    assert path == str(audio)
    assert kwargs["path_or_hf_repo"] == "some/model"
    assert kwargs["language"] == "yue"
    assert "OpenAI" in kwargs["initial_prompt"]
    assert kwargs["verbose"] is False


def test_auto_language_lets_whisper_detect_and_empty_prompt_is_omitted(tmp_path):
    fake = FakeMlx({"language": "en", "segments": []})
    transcriber = MlxWhisperTranscriber("m", transcribe_fn=fake)

    result = transcriber.transcribe(tmp_path / "a.webm", "en", "")
    assert fake.calls[0][1]["initial_prompt"] is None

    transcriber.transcribe(tmp_path / "a.webm", "auto", "")
    assert fake.calls[1][1]["language"] is None
    assert result.segments == [] and result.duration_s == 0.0


@pytest.mark.mac
def test_real_whisper_runs_on_a_short_clip(tmp_path):
    """Mac only: loads the real model. Run with: pytest -m mac"""
    import math
    import struct
    import wave

    pytest.importorskip("mlx_whisper")
    clip = tmp_path / "tone.wav"
    with wave.open(str(clip), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(
            b"".join(
                struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * n / 16000)))
                for n in range(16000 * 3)
            )
        )
    result = MlxWhisperTranscriber("mlx-community/whisper-large-v3-turbo").transcribe(clip, "en", "")
    assert result.duration_s >= 0.0
