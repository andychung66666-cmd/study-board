from pathlib import Path

import uvicorn

from talkboard.config import load_settings
from talkboard.server import create_app


def main() -> None:
    settings = load_settings(Path("talkboard.toml"))
    print(f"Talk Summary: open http://{settings.host}:{settings.port} in Chrome")
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
