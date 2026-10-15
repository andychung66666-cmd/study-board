from talkboard.storage import NoAudio, TalkStorage

import pytest


def test_finalizing_twice_keeps_the_same_audio(tmp_path):
    """A crash between joining the chunks and updating the database must not lose the audio."""
    storage = TalkStorage(tmp_path)
    storage.store_chunk(1, 0, b"abc")
    storage.store_chunk(1, 1, b"def")
    first = storage.finalize(1)
    second = storage.finalize(1)
    assert first == second
    assert second.read_bytes() == b"abcdef"


def test_finalizing_with_nothing_recorded_still_fails(tmp_path):
    with pytest.raises(NoAudio):
        TalkStorage(tmp_path).finalize(7)
