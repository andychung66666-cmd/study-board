import queue
import threading
from pathlib import Path

from talkboard.db import Database, Status
from talkboard.storage import TalkStorage

PENDING = (Status.RECORDED, Status.TRANSCRIBING, Status.SUMMARISING)


class JobRunner:
    """Runs one talk at a time: transcribe, then summarise.

    process() reads the talk's status to decide what is left to do, so a talk
    that was interrupted by a restart or retried after a failure resumes
    correctly without any special cases.
    """

    def __init__(self, db: Database, storage: TalkStorage, transcriber, summariser=None):
        self.db = db
        self.storage = storage
        self.transcriber = transcriber
        self.summariser = summariser
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def enqueue(self, talk_id: int) -> None:
        self._queue.put(talk_id)

    def recover_pending(self) -> list[int]:
        ids = [talk.id for talk in self.db.list_talks() if talk.status in PENDING]
        for talk_id in ids:
            self.enqueue(talk_id)
        return ids

    def run_pending(self) -> None:
        while True:
            try:
                talk_id = self._queue.get_nowait()
            except queue.Empty:
                return
            if talk_id is not None:
                self.process(talk_id)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._work, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread:
            self._queue.put(None)
            self._thread.join(timeout=10)
            self._thread = None

    def _work(self) -> None:
        while (talk_id := self._queue.get()) is not None:
            self.process(talk_id)

    def process(self, talk_id: int) -> None:
        talk = self.db.get_talk(talk_id)
        if talk is None or talk.status not in PENDING:
            return
        try:
            if talk.status in (Status.RECORDED, Status.TRANSCRIBING):
                self._transcribe(talk)
            self._summarise(talk_id)
        except Exception as error:
            self.db.set_status(talk_id, Status.FAILED, error=f"{type(error).__name__}: {error}")

    def _transcribe(self, talk) -> None:
        if talk.status is Status.RECORDED:
            self.db.set_status(talk.id, Status.TRANSCRIBING)
        if self.transcriber is None:
            raise RuntimeError("No transcriber configured")
        self.db.clear_segments(talk.id)
        result = self.transcriber.transcribe(Path(talk.audio_path), talk.language, talk.word_list)
        self.db.add_segments(talk.id, [(s.start, s.end, s.text) for s in result.segments])
        self.db.set_duration(talk.id, result.duration_s)
        self.db.set_status(talk.id, Status.SUMMARISING)

    def _summarise(self, talk_id: int) -> None:
        if self.summariser is not None:
            talk = self.db.get_talk(talk_id)
            result = self.summariser.summarise(talk, self.db.get_segments(talk_id))
            self.db.save_summary(talk_id, result.engine, result.model, result.body)
        self.db.set_status(talk_id, Status.DONE)
