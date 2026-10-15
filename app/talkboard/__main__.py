from pathlib import Path

import uvicorn

from talkboard.config import load_settings
from talkboard.server import create_app
from talkboard.transcribe import MlxWhisperTranscriber


def main() -> None:
    settings = load_settings(Path("talkboard.toml"))
    print(f"Talk Summary: open http://{settings.host}:{settings.port} in Chrome")
    transcriber = MlxWhisperTranscriber(settings.whisper_model)
    uvicorn.run(
        create_app(settings, transcriber=transcriber), host=settings.host, port=settings.port
    )


if __name__ == "__main__":
    main()
