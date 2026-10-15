from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from talkboard.config import Settings
from talkboard.db import Database, Status
from talkboard.jobs import JobRunner
from talkboard.storage import ChunkGap, NoAudio, TalkStorage


class NewTalk(BaseModel):
    title: str
    source: Literal["mic", "tab"]
    language: str
    word_list: str = ""


def create_app(
    settings: Settings, transcriber=None, summariser=None, start_worker: bool = True
) -> FastAPI:
    app = FastAPI(title="Talk Summary")
    app.state.settings = settings
    app.state.db = Database(settings.data_dir / "talkboard.sqlite")
    app.state.storage = TalkStorage(settings.data_dir)
    app.state.runner = JobRunner(app.state.db, app.state.storage, transcriber, summariser)
    if start_worker:
        app.state.runner.recover_pending()
        app.state.runner.start()

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

    def talk_row(talk) -> dict:
        return {
            "id": talk.id,
            "title": talk.title,
            "created_at": talk.created_at,
            "source": talk.source,
            "language": talk.language,
            "status": talk.status.value,
            "duration_s": talk.duration_s,
            "error": talk.error,
        }

    def existing_talk(talk_id: int):
        talk = app.state.db.get_talk(talk_id)
        if talk is None:
            raise HTTPException(404, "Unknown talk")
        return talk

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

    @app.get("/api/talks")
    def list_talks() -> list[dict]:
        return [talk_row(talk) for talk in app.state.db.list_talks()]

    @app.get("/api/talks/{talk_id}")
    def talk_detail(talk_id: int) -> dict:
        talk = existing_talk(talk_id)
        db = app.state.db
        idle = (
            app.state.storage.idle_seconds(talk_id) if talk.status is Status.RECORDING else None
        )
        return {
            **talk_row(talk),
            "word_list": talk.word_list,
            "audio_url": f"/api/talks/{talk_id}/audio" if talk.audio_path else None,
            "idle_s": idle,
            "segments": [
                {"start": s.start_s, "end": s.end_s, "text": s.text}
                for s in db.get_segments(talk_id)
            ],
            "summaries": [
                {"engine": s.engine, "model": s.model, "created_at": s.created_at, "body": s.body}
                for s in db.get_summaries(talk_id)
            ],
        }

    @app.get("/api/talks/{talk_id}/audio")
    def talk_audio(talk_id: int) -> FileResponse:
        talk = existing_talk(talk_id)
        if not talk.audio_path:
            raise HTTPException(404, "No audio for this talk yet")
        return FileResponse(talk.audio_path, media_type="audio/webm")

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

    def finish_recording(talk_id: int) -> dict:
        recording_talk(talk_id)
        try:
            audio = app.state.storage.finalize(talk_id)
        except NoAudio as error:
            raise HTTPException(409, str(error))
        app.state.db.set_audio_path(talk_id, str(audio))
        app.state.db.set_status(talk_id, Status.RECORDED)
        app.state.runner.enqueue(talk_id)
        return {"id": talk_id, "status": Status.RECORDED.value}

    @app.post("/api/talks/{talk_id}/stop")
    def stop_talk(talk_id: int) -> dict:
        return finish_recording(talk_id)

    @app.post("/api/talks/{talk_id}/recover")
    def recover_talk(talk_id: int) -> dict:
        """Finish a talk whose page died mid-recording: join what was uploaded and process it."""
        return finish_recording(talk_id)

    @app.post("/api/talks/{talk_id}/retry")
    def retry_talk(talk_id: int) -> dict:
        talk = app.state.db.get_talk(talk_id)
        if talk is None:
            raise HTTPException(404, "Unknown talk")
        if talk.status is not Status.FAILED:
            raise HTTPException(409, "Talk has not failed")
        resume = Status.SUMMARISING if app.state.db.get_segments(talk_id) else Status.RECORDED
        app.state.db.set_status(talk_id, resume)
        app.state.runner.enqueue(talk_id)
        return {"id": talk_id, "status": resume.value}

    app.mount(
        "/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static"
    )
    return app
