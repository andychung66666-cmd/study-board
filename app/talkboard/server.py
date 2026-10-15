from fastapi import FastAPI

from talkboard.config import Settings


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Talk Summary")
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    return app
