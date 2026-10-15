import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

SOURCES = ("mic", "tab")


class Status(str, Enum):
    RECORDING = "recording"
    RECORDED = "recorded"
    TRANSCRIBING = "transcribing"
    SUMMARISING = "summarising"
    DONE = "done"
    FAILED = "failed"


ALLOWED = {
    Status.RECORDING: {Status.RECORDED},
    Status.RECORDED: {Status.TRANSCRIBING},
    Status.TRANSCRIBING: {Status.SUMMARISING},
    Status.SUMMARISING: {Status.DONE},
    # A failed talk is retried from the start, or from the summary if the transcript exists.
    Status.FAILED: {Status.RECORDED, Status.SUMMARISING},
}


class InvalidTransition(Exception):
    pass


@dataclass(frozen=True)
class Talk:
    id: int
    title: str
    created_at: str
    source: str
    language: str
    word_list: str
    status: Status
    duration_s: float | None
    audio_path: str | None
    error: str | None


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    text: str


@dataclass(frozen=True)
class Summary:
    engine: str
    model: str
    created_at: str
    body: dict


SCHEMA = """
CREATE TABLE IF NOT EXISTS talks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    language TEXT NOT NULL,
    word_list TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    duration_s REAL,
    audio_path TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talk_id INTEGER NOT NULL REFERENCES talks(id) ON DELETE CASCADE,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS segments_by_talk ON segments(talk_id, start_s);
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talk_id INTEGER NOT NULL REFERENCES talks(id) ON DELETE CASCADE,
    engine TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    body TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _talk(row: sqlite3.Row) -> Talk:
    return Talk(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        source=row["source"],
        language=row["language"],
        word_list=row["word_list"],
        status=Status(row["status"]),
        duration_s=row["duration_s"],
        audio_path=row["audio_path"],
        error=row["error"],
    )


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create_talk(self, title: str, source: str, language: str, word_list: str = "") -> Talk:
        if source not in SOURCES:
            raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO talks (title, created_at, source, language, word_list, status)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (title, _now(), source, language, word_list, Status.RECORDING.value),
            )
            talk_id = cursor.lastrowid
        return self.get_talk(talk_id)

    def get_talk(self, talk_id: int) -> Talk | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM talks WHERE id = ?", (talk_id,)).fetchone()
        return _talk(row) if row else None

    def list_talks(self) -> list[Talk]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM talks ORDER BY id DESC").fetchall()
        return [_talk(row) for row in rows]

    def set_status(self, talk_id: int, status: Status, error: str | None = None) -> None:
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM talks WHERE id = ?", (talk_id,)).fetchone()
            if row is None:
                raise KeyError(talk_id)
            current = Status(row["status"])
            allowed = status is Status.FAILED and current is not Status.DONE
            allowed = allowed or status in ALLOWED.get(current, set())
            if not allowed:
                raise InvalidTransition(f"{current.value} -> {status.value}")
            conn.execute(
                "UPDATE talks SET status = ?, error = ? WHERE id = ?",
                (status.value, error, talk_id),
            )

    def set_audio_path(self, talk_id: int, audio_path: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE talks SET audio_path = ? WHERE id = ?", (audio_path, talk_id))

    def set_duration(self, talk_id: int, duration_s: float) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE talks SET duration_s = ? WHERE id = ?", (duration_s, talk_id))

    def clear_segments(self, talk_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM segments WHERE talk_id = ?", (talk_id,))

    def add_segments(self, talk_id: int, segments: list[tuple[float, float, str]]) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO segments (talk_id, start_s, end_s, text) VALUES (?, ?, ?, ?)",
                [(talk_id, start, end, text) for start, end, text in segments],
            )

    def get_segments(self, talk_id: int) -> list[Segment]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT start_s, end_s, text FROM segments WHERE talk_id = ? ORDER BY start_s",
                (talk_id,),
            ).fetchall()
        return [Segment(r["start_s"], r["end_s"], r["text"]) for r in rows]

    def save_summary(self, talk_id: int, engine: str, model: str, body: dict) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO summaries (talk_id, engine, model, created_at, body)"
                " VALUES (?, ?, ?, ?, ?)",
                (talk_id, engine, model, _now(), json.dumps(body, ensure_ascii=False)),
            )

    def get_summaries(self, talk_id: int) -> list[Summary]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT engine, model, created_at, body FROM summaries"
                " WHERE talk_id = ? ORDER BY id",
                (talk_id,),
            ).fetchall()
        return [Summary(r["engine"], r["model"], r["created_at"], json.loads(r["body"])) for r in rows]

    def delete_talk(self, talk_id: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM talks WHERE id = ?", (talk_id,))
