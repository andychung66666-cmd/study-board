import pytest

from talkboard.db import Database, InvalidTransition, Status


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "talks.sqlite")


def new_talk(db, **overrides):
    values = dict(title="Keynote", source="mic", language="auto", word_list="")
    values.update(overrides)
    return db.create_talk(**values)


def test_new_talk_starts_in_recording_status(db):
    talk = new_talk(db, title="Intro to AI", source="tab", language="yue", word_list="OpenAI")
    fetched = db.get_talk(talk.id)
    assert fetched.title == "Intro to AI"
    assert fetched.source == "tab"
    assert fetched.language == "yue"
    assert fetched.word_list == "OpenAI"
    assert fetched.status is Status.RECORDING
    assert fetched.created_at


def test_unknown_audio_source_is_rejected(db):
    with pytest.raises(ValueError, match="source"):
        new_talk(db, source="phone")


def test_get_talk_returns_none_for_unknown_id(db):
    assert db.get_talk(999) is None


def test_talks_are_listed_newest_first(db):
    first = new_talk(db, title="first")
    second = new_talk(db, title="second")
    assert [t.id for t in db.list_talks()] == [second.id, first.id]


def test_status_moves_forward_through_the_pipeline(db):
    talk = new_talk(db)
    for status in (Status.RECORDED, Status.TRANSCRIBING, Status.SUMMARISING, Status.DONE):
        db.set_status(talk.id, status)
        assert db.get_talk(talk.id).status is status


@pytest.mark.parametrize(
    "start, target",
    [
        (Status.RECORDING, Status.DONE),
        (Status.RECORDED, Status.SUMMARISING),
        (Status.TRANSCRIBING, Status.RECORDING),
        (Status.DONE, Status.RECORDING),
    ],
)
def test_illegal_status_jump_is_refused_and_leaves_status_alone(db, start, target):
    talk = new_talk(db)
    with db.connect() as conn:
        conn.execute("UPDATE talks SET status = ? WHERE id = ?", (start.value, talk.id))
    with pytest.raises(InvalidTransition):
        db.set_status(talk.id, target)
    assert db.get_talk(talk.id).status is start


def test_any_active_status_can_fail_and_keeps_the_error_text(db):
    talk = new_talk(db)
    db.set_status(talk.id, Status.RECORDED)
    db.set_status(talk.id, Status.FAILED, error="ffmpeg not found")
    fetched = db.get_talk(talk.id)
    assert fetched.status is Status.FAILED
    assert fetched.error == "ffmpeg not found"


def test_segments_come_back_in_time_order(db):
    talk = new_talk(db)
    db.add_segments(talk.id, [(10.0, 15.0, "second"), (0.0, 5.0, "first"), (20.0, 25.0, "third")])
    assert [s.text for s in db.get_segments(talk.id)] == ["first", "second", "third"]


def test_summaries_keep_engine_and_body(db):
    talk = new_talk(db)
    db.save_summary(talk.id, engine="local", model="qwen", body={"tldr": ["a", "b", "c"]})
    db.save_summary(talk.id, engine="claude", model="claude-x", body={"tldr": ["x"]})
    summaries = db.get_summaries(talk.id)
    assert [s.engine for s in summaries] == ["local", "claude"]
    assert summaries[0].body == {"tldr": ["a", "b", "c"]}


def test_deleting_a_talk_removes_its_segments_and_summaries(db):
    talk = new_talk(db)
    other = new_talk(db, title="keep me")
    db.add_segments(talk.id, [(0.0, 1.0, "gone")])
    db.add_segments(other.id, [(0.0, 1.0, "stays")])
    db.save_summary(talk.id, engine="local", model="m", body={})
    db.delete_talk(talk.id)
    assert db.get_talk(talk.id) is None
    assert db.get_segments(talk.id) == []
    assert db.get_summaries(talk.id) == []
    assert [s.text for s in db.get_segments(other.id)] == ["stays"]


def test_a_failed_talk_can_be_retried_from_the_start_or_from_summarising(db):
    talk = new_talk(db)
    for retry in (Status.RECORDED, Status.SUMMARISING):
        with db.connect() as conn:
            conn.execute("UPDATE talks SET status = 'failed', error = 'x' WHERE id = ?", (talk.id,))
        db.set_status(talk.id, retry)
        fetched = db.get_talk(talk.id)
        assert fetched.status is retry
        assert fetched.error is None


def test_a_failed_talk_cannot_jump_straight_to_done(db):
    talk = new_talk(db)
    with db.connect() as conn:
        conn.execute("UPDATE talks SET status = 'failed' WHERE id = ?", (talk.id,))
    with pytest.raises(InvalidTransition):
        db.set_status(talk.id, Status.DONE)


def test_clearing_segments_removes_only_that_talks_lines(db):
    first, second = new_talk(db), new_talk(db)
    db.add_segments(first.id, [(0.0, 1.0, "a")])
    db.add_segments(second.id, [(0.0, 1.0, "b")])
    db.clear_segments(first.id)
    assert db.get_segments(first.id) == []
    assert [s.text for s in db.get_segments(second.id)] == ["b"]


def test_duration_is_stored_on_the_talk(db):
    talk = new_talk(db)
    db.set_duration(talk.id, 123.5)
    assert db.get_talk(talk.id).duration_s == 123.5
