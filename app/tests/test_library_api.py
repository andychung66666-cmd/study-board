import os
import time

import pytest
from fastapi.testclient import TestClient

from talkboard.config import Settings
from talkboard.db import Status
from talkboard.server import create_app

AUDIO = b"0123456789abcdef"


@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path), start_worker=False)


@pytest.fixture
def client(app):
    return TestClient(app, base_url="http://127.0.0.1:8765")


def make_done_talk(app, title="Talk", segments=(), summary=None, audio=AUDIO):
    db, storage = app.state.db, app.state.storage
    talk = db.create_talk(title, "mic", "yue", "OpenAI")
    storage.store_chunk(talk.id, 0, audio)
    db.set_audio_path(talk.id, str(storage.finalize(talk.id)))
    for status in (Status.RECORDED, Status.TRANSCRIBING, Status.SUMMARISING, Status.DONE):
        db.set_status(talk.id, status)
    db.add_segments(talk.id, list(segments))
    db.set_duration(talk.id, 125.0)
    if summary:
        db.save_summary(talk.id, "local", "qwen", summary)
    return talk


def test_talks_are_listed_newest_first_with_status_and_duration(app, client):
    first = make_done_talk(app, "First")
    second = app.state.db.create_talk("Second", "tab", "en", "")
    rows = client.get("/api/talks").json()
    assert [r["id"] for r in rows] == [second.id, first.id]
    assert rows[1] == {
        "id": first.id,
        "title": "First",
        "created_at": rows[1]["created_at"],
        "source": "mic",
        "language": "yue",
        "status": "done",
        "duration_s": 125.0,
        "error": None,
    }
    assert rows[0]["status"] == "recording"


def test_talk_detail_has_ordered_segments_summaries_and_audio_link(app, client):
    talk = make_done_talk(
        app,
        segments=[(10.0, 12.0, "second"), (0.0, 4.0, "first")],
        summary={"tldr": ["a", "b", "c"]},
    )
    detail = client.get(f"/api/talks/{talk.id}").json()
    assert [s["text"] for s in detail["segments"]] == ["first", "second"]
    assert detail["segments"][0] == {"start": 0.0, "end": 4.0, "text": "first"}
    assert detail["summaries"][0]["body"] == {"tldr": ["a", "b", "c"]}
    assert detail["summaries"][0]["engine"] == "local"
    assert detail["audio_url"] == f"/api/talks/{talk.id}/audio"
    assert detail["word_list"] == "OpenAI"


def test_unknown_talk_is_404_for_detail_and_audio(client):
    for path in ("/api/talks/999", "/api/talks/999/audio"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()["detail"] == "Unknown talk"


def test_a_talk_still_recording_has_no_audio_link_or_audio(app, client):
    talk = app.state.db.create_talk("Live", "mic", "en", "")
    assert client.get(f"/api/talks/{talk.id}").json()["audio_url"] is None
    assert client.get(f"/api/talks/{talk.id}/audio").status_code == 404


def test_audio_is_served_whole_with_its_type(app, client):
    talk = make_done_talk(app)
    response = client.get(f"/api/talks/{talk.id}/audio")
    assert response.status_code == 200
    assert response.content == AUDIO
    assert response.headers["content-type"].startswith("audio/webm")
    assert response.headers["accept-ranges"] == "bytes"


def test_audio_supports_range_requests_so_the_player_can_seek(app, client):
    talk = make_done_talk(app)
    response = client.get(f"/api/talks/{talk.id}/audio", headers={"range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == AUDIO[2:6]
    assert response.headers["content-range"] == f"bytes 2-5/{len(AUDIO)}"


def test_recording_talk_reports_seconds_since_the_last_chunk(app, client):
    talk = app.state.db.create_talk("Live", "mic", "en", "")
    app.state.storage.store_chunk(talk.id, 0, b"x")
    assert client.get(f"/api/talks/{talk.id}").json()["idle_s"] < 5

    part = next(app.state.storage.talk_dir(talk.id).glob("part-*"))
    old = time.time() - 120
    os.utime(part, (old, old))
    assert client.get(f"/api/talks/{talk.id}").json()["idle_s"] >= 119


def test_idle_seconds_are_only_reported_for_recording_talks(app, client):
    talk = make_done_talk(app)
    assert client.get(f"/api/talks/{talk.id}").json()["idle_s"] is None
