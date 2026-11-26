import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Iterator

from backend.events.schema import EventEnvelope, RUN_ID_PATTERN


@dataclass(frozen=True)
class StoredEvent:
    sequence: int
    event: EventEnvelope


class EventStore:
    def __init__(self, database_path: Path, runs_dir: Path) -> None:
        self.database_path = database_path
        self.runs_dir = runs_dir
        self._lock = threading.RLock()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    UNIQUE(run_id, id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS events_by_run_sequence "
                "ON events(run_id, sequence)"
            )

    def append(self, event: EventEnvelope) -> StoredEvent:
        self._validate_run_id(event.run_id)
        event_json = event.model_dump_json()
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO events (id, run_id, event_json) VALUES (?, ?, ?)",
                (event.id, event.run_id, event_json),
            )
            sequence = int(cursor.lastrowid)
            run_log = self.runs_dir / event.run_id / "events.jsonl"
            run_log.parent.mkdir(parents=True, exist_ok=True)
            with run_log.open("a", encoding="utf-8") as log:
                log.write(event_json + "\n")
        return StoredEvent(sequence=sequence, event=event)

    def snapshot(self, run_id: str, after_id: str | None = None) -> tuple[int, list[StoredEvent]]:
        self._validate_run_id(run_id)
        with self._lock, self._connection() as connection:
            high_water = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            cursor_sequence = 0
            if after_id is not None:
                cursor = connection.execute(
                    "SELECT sequence FROM events WHERE run_id = ? AND id = ?",
                    (run_id, after_id),
                ).fetchone()
                if cursor is None:
                    raise ValueError("after cursor was not found for this run")
                cursor_sequence = int(cursor[0])

            rows = connection.execute(
                """
                SELECT sequence, event_json FROM events
                WHERE run_id = ? AND sequence > ? AND sequence <= ?
                ORDER BY sequence
                """,
                (run_id, cursor_sequence, high_water),
            ).fetchall()
        return high_water, [
            StoredEvent(
                sequence=int(sequence),
                event=EventEnvelope.model_validate_json(event_json),
            )
            for sequence, event_json in rows
        ]

    def replay(self, run_id: str, after_id: str | None = None) -> list[EventEnvelope]:
        _, events = self.snapshot(run_id, after_id)
        return [stored.event for stored in events]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _validate_run_id(run_id: str) -> None:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ValueError("run_id must contain 1-64 letters, digits, underscores, or hyphens")
