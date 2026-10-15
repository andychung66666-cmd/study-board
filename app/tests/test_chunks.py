import pytest
from fastapi.testclient import TestClient

from talkboard.config import Settings
from talkboard.db import Status
from talkboard.server import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(data_dir=tmp_path)), base_url="http://127.0.0.1:8765")


def start_talk(client, **overrides):
    body = dict(title="Keynote", source="mic", language="yue", word_list="OpenAI")
    body.update(overrides)
    response = client.post("/api/talks", json=body)
    assert response.status_code == 201
    return response.json()["id"]


def put_chunk(client, talk_id, index, data):
    return client.put(
        f"/api/talks/{talk_id}/chunks/{index}",
        content=data,
        headers={"content-type": "application/octet-stream"},
    )


def test_creating_a_talk_returns_its_id_and_recording_status(client):
    response = client.post(
        "/api/talks",
        json=dict(title="Keynote", source="tab", language="en", word_list=""),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "recording"
    assert client.app.state.db.get_talk(body["id"]).source == "tab"


def test_creating_a_talk_with_an_unknown_source_is_rejected(client):
    response = client.post(
        "/api/talks",
        json=dict(title="x", source="phone", language="en", word_list=""),
    )
    assert response.status_code == 422


def test_stop_joins_chunks_into_one_file_byte_for_byte(client):
    talk_id = start_talk(client)
    chunks = [b"\x1aE\xdf\xa3first", b"\x00\x01second", b"third\xff"]
    for index, data in enumerate(chunks):
        assert put_chunk(client, talk_id, index, data).status_code == 204

    response = client.post(f"/api/talks/{talk_id}/stop")

    assert response.status_code == 200
    talk = client.app.state.db.get_talk(talk_id)
    assert talk.status is Status.RECORDED
    with open(talk.audio_path, "rb") as audio:
        assert audio.read() == b"".join(chunks)


def test_uploading_the_same_chunk_index_again_is_ignored(client):
    talk_id = start_talk(client)
    put_chunk(client, talk_id, 0, b"original")
    assert put_chunk(client, talk_id, 0, b"retry-with-other-bytes").status_code == 204
    put_chunk(client, talk_id, 1, b"-next")

    client.post(f"/api/talks/{talk_id}/stop")

    talk = client.app.state.db.get_talk(talk_id)
    with open(talk.audio_path, "rb") as audio:
        assert audio.read() == b"original-next"


def test_a_chunk_that_skips_an_index_is_rejected_with_409(client):
    talk_id = start_talk(client)
    put_chunk(client, talk_id, 0, b"a")
    response = put_chunk(client, talk_id, 2, b"c")
    assert response.status_code == 409
    assert "1" in response.json()["detail"]


def test_stop_with_no_chunks_fails_and_the_talk_keeps_recording(client):
    talk_id = start_talk(client)
    response = client.post(f"/api/talks/{talk_id}/stop")
    assert response.status_code == 409
    assert client.app.state.db.get_talk(talk_id).status is Status.RECORDING


def test_chunk_for_an_unknown_talk_is_404(client):
    response = put_chunk(client, 999, 0, b"a")
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown talk"


def test_chunks_after_stop_are_refused(client):
    talk_id = start_talk(client)
    put_chunk(client, talk_id, 0, b"a")
    client.post(f"/api/talks/{talk_id}/stop")
    assert put_chunk(client, talk_id, 1, b"b").status_code == 409


def test_stopping_twice_is_refused_and_does_not_change_the_audio(client):
    talk_id = start_talk(client)
    put_chunk(client, talk_id, 0, b"abc")
    client.post(f"/api/talks/{talk_id}/stop")
    assert client.post(f"/api/talks/{talk_id}/stop").status_code == 409
    talk = client.app.state.db.get_talk(talk_id)
    with open(talk.audio_path, "rb") as audio:
        assert audio.read() == b"abc"
