import threading
import time

import pytest
from fastapi.testclient import TestClient

from talkboard.config import Settings
from talkboard.db import Database, Status
from talkboard.jobs import JobRunner
from talkboard.server import create_app
from talkboard.storage import TalkStorage
from talkboard.summarise import SummaryResult
from talkboard.transcribe import Seg, TranscriptResult

SEGMENTS = [Seg(0.0, 4.0, "hello"), Seg(4.0, 9.5, "world")]


class FakeTranscriber:
    def __init__(self, segments=SEGMENTS, error=None, delay=0.0):
        self.segments = segments
        self.error = error
        self.delay = delay
        self.calls = []
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()

    def transcribe(self, audio_path, language, word_list):
        self.calls.append((str(audio_path), language, word_list))
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(self.delay)
            if self.error:
                raise self.error
            return TranscriptResult(self.segments, duration_s=9.5, language="zh")
        finally:
            with self._lock:
                self._active -= 1


class FakeSummariser:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def summarise(self, talk, segments):
        self.calls.append((talk.id, [s.text for s in segments]))
        if self.error:
            raise self.error
        return SummaryResult(engine="local", model="fake", body={"tldr": ["x"]})


@pytest.fixture
def parts(tmp_path):
    return Database(tmp_path / "t.sqlite"), TalkStorage(tmp_path)


def recorded_talk(db, storage, language="yue", word_list="OpenAI"):
    talk = db.create_talk("Talk", "mic", language, word_list)
    storage.store_chunk(talk.id, 0, b"audio-bytes")
    db.set_audio_path(talk.id, str(storage.finalize(talk.id)))
    db.set_status(talk.id, Status.RECORDED)
    return talk


def set_status(db, talk_id, status):
    with db.connect() as conn:
        conn.execute("UPDATE talks SET status = ? WHERE id = ?", (status.value, talk_id))


def test_a_recorded_talk_is_transcribed_summarised_and_done(parts):
    db, storage = parts
    transcriber, summariser = FakeTranscriber(), FakeSummariser()
    runner = JobRunner(db, storage, transcriber, summariser)
    talk = recorded_talk(db, storage)

    runner.enqueue(talk.id)
    runner.run_pending()

    done = db.get_talk(talk.id)
    assert done.status is Status.DONE
    assert done.duration_s == 9.5
    assert [s.text for s in db.get_segments(talk.id)] == ["hello", "world"]
    assert transcriber.calls == [(done.audio_path, "yue", "OpenAI")]
    assert summariser.calls == [(talk.id, ["hello", "world"])]
    assert db.get_summaries(talk.id)[0].body == {"tldr": ["x"]}


def test_without_a_summariser_the_talk_still_finishes_with_its_transcript(parts):
    db, storage = parts
    runner = JobRunner(db, storage, FakeTranscriber())
    talk = recorded_talk(db, storage)
    runner.enqueue(talk.id)
    runner.run_pending()
    assert db.get_talk(talk.id).status is Status.DONE
    assert db.get_summaries(talk.id) == []


def test_two_talks_are_never_transcribed_at_the_same_time(parts):
    db, storage = parts
    transcriber = FakeTranscriber(delay=0.15)
    runner = JobRunner(db, storage, transcriber)
    first, second = recorded_talk(db, storage), recorded_talk(db, storage)
    runner.start()
    try:
        runner.enqueue(first.id)
        runner.enqueue(second.id)
        deadline = time.time() + 5
        while not all(db.get_talk(t.id).status is Status.DONE for t in (first, second)):
            assert time.time() < deadline, "jobs did not finish"
            time.sleep(0.02)
    finally:
        runner.stop()
    assert transcriber.max_active == 1


def test_a_failing_transcriber_marks_the_talk_failed_with_the_error(parts):
    db, storage = parts
    runner = JobRunner(db, storage, FakeTranscriber(error=RuntimeError("model missing")))
    talk = recorded_talk(db, storage)
    runner.enqueue(talk.id)
    runner.run_pending()
    failed = db.get_talk(talk.id)
    assert failed.status is Status.FAILED
    assert "model missing" in failed.error


def test_a_failing_summariser_keeps_the_transcript(parts):
    db, storage = parts
    runner = JobRunner(
        db, storage, FakeTranscriber(), FakeSummariser(error=ConnectionError("ollama down"))
    )
    talk = recorded_talk(db, storage)
    runner.enqueue(talk.id)
    runner.run_pending()
    failed = db.get_talk(talk.id)
    assert failed.status is Status.FAILED
    assert "ollama down" in failed.error
    assert len(db.get_segments(talk.id)) == 2


def test_startup_requeues_interrupted_talks_without_duplicating_work(parts):
    db, storage = parts
    transcriber, summariser = FakeTranscriber(), FakeSummariser()
    runner = JobRunner(db, storage, transcriber, summariser)

    mid_transcription = recorded_talk(db, storage)
    set_status(db, mid_transcription.id, Status.TRANSCRIBING)
    db.add_segments(mid_transcription.id, [(0.0, 1.0, "stale half-result")])

    mid_summary = recorded_talk(db, storage)
    set_status(db, mid_summary.id, Status.SUMMARISING)
    db.add_segments(mid_summary.id, [(0.0, 1.0, "kept transcript")])

    finished = recorded_talk(db, storage)
    set_status(db, finished.id, Status.DONE)

    assert sorted(runner.recover_pending()) == sorted([mid_transcription.id, mid_summary.id])
    runner.run_pending()

    assert [s.text for s in db.get_segments(mid_transcription.id)] == ["hello", "world"]
    assert [s.text for s in db.get_segments(mid_summary.id)] == ["kept transcript"]
    assert len(transcriber.calls) == 1  # only the talk that was mid-transcription
    assert sorted(c[0] for c in summariser.calls) == sorted([mid_transcription.id, mid_summary.id])
    assert db.get_talk(finished.id).status is Status.DONE


# ---- routes: stop, recover, retry -------------------------------------------------


@pytest.fixture
def app_parts(tmp_path):
    transcriber, summariser = FakeTranscriber(), FakeSummariser()
    app = create_app(
        Settings(data_dir=tmp_path),
        transcriber=transcriber,
        summariser=summariser,
        start_worker=False,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return client, app, transcriber, summariser


def upload(client, chunks=(b"abc",), stop=True):
    talk_id = client.post(
        "/api/talks",
        json=dict(title="T", source="mic", language="en", word_list=""),
    ).json()["id"]
    for index, data in enumerate(chunks):
        client.put(f"/api/talks/{talk_id}/chunks/{index}", content=data)
    if stop:
        client.post(f"/api/talks/{talk_id}/stop")
    return talk_id


def test_stopping_a_talk_queues_it_for_processing(app_parts):
    client, app, transcriber, _ = app_parts
    talk_id = upload(client)
    app.state.runner.run_pending()
    assert app.state.db.get_talk(talk_id).status is Status.DONE
    assert len(transcriber.calls) == 1


def test_recover_finishes_a_talk_whose_tab_died_while_recording(app_parts):
    client, app, _, _ = app_parts
    talk_id = upload(client, chunks=(b"one", b"two"), stop=False)
    assert app.state.db.get_talk(talk_id).status is Status.RECORDING

    assert client.post(f"/api/talks/{talk_id}/recover").status_code == 200
    app.state.runner.run_pending()

    talk = app.state.db.get_talk(talk_id)
    assert talk.status is Status.DONE
    with open(talk.audio_path, "rb") as audio:
        assert audio.read() == b"onetwo"


def test_recover_is_refused_for_a_talk_that_is_not_stuck_recording(app_parts):
    client, app, _, _ = app_parts
    talk_id = upload(client)
    assert client.post(f"/api/talks/{talk_id}/recover").status_code == 409


def test_recover_with_no_audio_at_all_is_refused(app_parts):
    client, app, _, _ = app_parts
    talk_id = upload(client, chunks=(), stop=False)
    assert client.post(f"/api/talks/{talk_id}/recover").status_code == 409


def test_retry_after_a_transcription_failure_starts_over(app_parts):
    client, app, transcriber, _ = app_parts
    transcriber.error = RuntimeError("boom")
    talk_id = upload(client)
    app.state.runner.run_pending()
    assert app.state.db.get_talk(talk_id).status is Status.FAILED

    transcriber.error = None
    assert client.post(f"/api/talks/{talk_id}/retry").status_code == 200
    app.state.runner.run_pending()

    assert app.state.db.get_talk(talk_id).status is Status.DONE
    assert len(transcriber.calls) == 2


def test_retry_after_a_summary_failure_only_summarises_again(app_parts):
    client, app, transcriber, summariser = app_parts
    summariser.error = ConnectionError("down")
    talk_id = upload(client)
    app.state.runner.run_pending()
    assert app.state.db.get_talk(talk_id).status is Status.FAILED

    summariser.error = None
    assert client.post(f"/api/talks/{talk_id}/retry").status_code == 200
    app.state.runner.run_pending()

    assert app.state.db.get_talk(talk_id).status is Status.DONE
    assert len(transcriber.calls) == 1  # transcript kept, not redone
    assert len(summariser.calls) == 2


def test_retry_is_refused_for_a_talk_that_has_not_failed(app_parts):
    client, app, _, _ = app_parts
    talk_id = upload(client)
    assert client.post(f"/api/talks/{talk_id}/retry").status_code == 409


def test_a_runner_with_no_transcriber_fails_the_talk_with_a_clear_message(parts):
    db, storage = parts
    runner = JobRunner(db, storage, transcriber=None)
    talk = recorded_talk(db, storage)
    runner.enqueue(talk.id)
    runner.run_pending()
    failed = db.get_talk(talk.id)
    assert failed.status is Status.FAILED
    assert "No transcriber configured" in failed.error
