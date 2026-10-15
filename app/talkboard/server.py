from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from talkboard.config import Settings
from talkboard.db import Database, Status
from talkboard.storage import ChunkGap, NoAudio, TalkStorage


class NewTalk(BaseModel):
    title: str
    source: Literal["mic", "tab"]
    language: str
    word_list: str = ""


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Talk Summary")
    app.state.settings = settings
    app.state.db = Database(settings.data_dir / "talkboard.sqlite")
    app.state.storage = TalkStorage(settings.data_dir)

    # No login, so the app must not answer pages on other sites. The Host check
    # blocks DNS rebinding; the Origin check blocks cross-site writes.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware("http")
    async def refuse_cross_site_writes(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if urlsplit(origin).hostname not in settings.allowed_hosts:
                return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
        return await call_next(request)

    def recording_talk(talk_id: int):
        talk = app.state.db.get_talk(talk_id)
        if talk is None:
            raise HTTPException(404, "Unknown talk")
        if talk.status is not Status.RECORDING:
            raise HTTPException(409, "Talk is not recording")
        return talk

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/talks", status_code=201)
    def create_talk(body: NewTalk) -> dict:
        talk = app.state.db.create_talk(
            body.title, body.source, body.language, body.word_list
        )
        return {"id": talk.id, "status": talk.status.value}

    @app.put("/api/talks/{talk_id}/chunks/{index}", status_code=204)
    async def put_chunk(talk_id: int, index: int, request: Request) -> Response:
        recording_talk(talk_id)
        try:
            app.state.storage.store_chunk(talk_id, index, await request.body())
        except ChunkGap as gap:
            raise HTTPException(409, str(gap))
        return Response(status_code=204)

    @app.post("/api/talks/{talk_id}/stop")
    def stop_talk(talk_id: int) -> dict:
        recording_talk(talk_id)
        try:
            audio = app.state.storage.finalize(talk_id)
        except NoAudio as error:
            raise HTTPException(409, str(error))
        app.state.db.set_audio_path(talk_id, str(audio))
        app.state.db.set_status(talk_id, Status.RECORDED)
        return {"id": talk_id, "status": Status.RECORDED.value}

    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static"
    )
    return app
