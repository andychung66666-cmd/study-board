import os
import time
from pathlib import Path


class ChunkGap(Exception):
    def __init__(self, expected: int, got: int):
        super().__init__(f"Chunk {got} skips ahead; next expected chunk is {expected}")
        self.expected = expected


class NoAudio(Exception):
    pass


class TalkStorage:
    """Keeps each uploaded chunk as its own file and joins them on stop.

    One file per chunk makes retries idempotent and means a crash can never
    leave a half-appended chunk in the audio.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    def talk_dir(self, talk_id: int) -> Path:
        return self.root / "talks" / str(talk_id)

    def audio_path(self, talk_id: int) -> Path:
        return self.talk_dir(talk_id) / "audio.webm"

    def _part(self, talk_id: int, index: int) -> Path:
        return self.talk_dir(talk_id) / f"part-{index:06d}"

    def _next_index(self, talk_id: int) -> int:
        index = 0
        while self._part(talk_id, index).exists():
            index += 1
        return index

    def store_chunk(self, talk_id: int, index: int, data: bytes) -> None:
        if self._part(talk_id, index).exists():
            return
        expected = self._next_index(talk_id)
        if index > expected:
            raise ChunkGap(expected, index)
        self.talk_dir(talk_id).mkdir(parents=True, exist_ok=True)
        part = self._part(talk_id, index)
        temp = part.with_suffix(".tmp")
        temp.write_bytes(data)
        os.replace(temp, part)

    def finalize(self, talk_id: int) -> Path:
        count = self._next_index(talk_id)
        audio = self.audio_path(talk_id)
        if count == 0:
            if audio.exists():  # already joined; the caller may be repeating after a crash
                return audio
            raise NoAudio("No audio was received for this talk")
        temp = audio.with_suffix(".tmp")
        with open(temp, "wb") as out:
            for index in range(count):
                out.write(self._part(talk_id, index).read_bytes())
        os.replace(temp, audio)
        for index in range(count):
            self._part(talk_id, index).unlink()
        return audio

    def idle_seconds(self, talk_id: int) -> float | None:
        """Seconds since this talk's newest file was written, or None if it has none."""
        folder = self.talk_dir(talk_id)
        if not folder.exists():
            return None
        times = [path.stat().st_mtime for path in folder.iterdir()]
        return time.time() - max(times) if times else None
