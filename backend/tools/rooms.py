from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
from typing import Iterator
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class Room(BaseModel):
    id: str
    name: str


ROOMS = (
    Room(id="whiteboard_room", name="Whiteboard Room"),
    Room(id="war_room", name="War Room"),
    Room(id="focus_room", name="Focus Room"),
)
ROOM_BY_ID = {room.id: room for room in ROOMS}


class RoomBooking(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    room_id: str
    organizer: str
    attendees: tuple[str, ...]
    topic: str
    starts_at: datetime
    ends_at: datetime
    status: str = "booked"


class RoomSchedule(BaseModel):
    room: Room
    schedule: list[RoomBooking]


class BookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organizer: str = Field(min_length=1, max_length=80)
    attendees: list[str] = Field(min_length=1, max_length=20)
    topic: str = Field(min_length=1, max_length=240)
    duration_minutes: int = Field(ge=1, le=480)
    starts_at: datetime | None = None


class BookingConflictError(ValueError):
    """Raised when a room or attendee is already booked for the requested time."""


class RoomBookingService:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS room_bookings (
                    id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    organizer TEXT NOT NULL,
                    attendees_json TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('booked', 'released'))
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS bookings_by_room_time "
                "ON room_bookings(room_id, starts_at, ends_at, status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS bookings_by_status_time "
                "ON room_bookings(status, starts_at, ends_at)"
            )

    def book_room(
        self,
        room_id: str,
        organizer: str,
        attendees: list[str] | tuple[str, ...],
        topic: str,
        duration_minutes: int,
        starts_at: datetime | None = None,
    ) -> RoomBooking:
        request = BookingRequest(
            organizer=organizer,
            attendees=list(attendees),
            topic=topic,
            duration_minutes=duration_minutes,
            starts_at=starts_at,
        )
        if room_id not in ROOM_BY_ID:
            raise ValueError(f"Unknown room: {room_id}")

        attendee_names = tuple(dict.fromkeys(
            [request.organizer.strip(), *(name.strip() for name in request.attendees)]
        ))
        if any(not name for name in attendee_names):
            raise ValueError("attendee names must not be blank")
        topic = request.topic.strip()
        if not topic:
            raise ValueError("topic must not be blank")
        start = request.starts_at or datetime.now(timezone.utc)
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("starts_at must include a timezone")
        start = start.astimezone(timezone.utc)
        end = start + timedelta(minutes=request.duration_minutes)
        booking = RoomBooking(
            id=str(uuid4()),
            room_id=room_id,
            organizer=request.organizer.strip(),
            attendees=attendee_names,
            topic=topic,
            starts_at=start,
            ends_at=end,
        )

        with self._lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            active_bookings = connection.execute(
                """
                SELECT id, room_id, organizer, attendees_json, topic, starts_at, ends_at, status
                FROM room_bookings
                WHERE status = 'booked' AND starts_at < ? AND ends_at > ?
                """,
                (end.isoformat(), start.isoformat()),
            ).fetchall()
            requested_attendees = set(attendee_names)
            for row in active_bookings:
                existing_attendees = set(self._booking_from_row(row).attendees)
                if row["room_id"] == room_id:
                    raise BookingConflictError(
                        f"{ROOM_BY_ID[room_id].name} is already booked for that time"
                    )
                overlap = requested_attendees.intersection(existing_attendees)
                if overlap:
                    names = ", ".join(sorted(overlap))
                    raise BookingConflictError(f"Attendee already booked for that time: {names}")

            connection.execute(
                """
                INSERT INTO room_bookings
                    (id, room_id, organizer, attendees_json, topic, starts_at, ends_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'booked')
                """,
                (
                    booking.id,
                    booking.room_id,
                    booking.organizer,
                    self._attendees_json(booking.attendees),
                    booking.topic,
                    booking.starts_at.isoformat(),
                    booking.ends_at.isoformat(),
                ),
            )
        return booking

    def release_room(self, booking_id: str, released_by: str) -> RoomBooking:
        with self._lock, self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE room_bookings SET status = 'released'
                WHERE id = ? AND organizer = ? AND status = 'booked'
                """,
                (booking_id, released_by.strip()),
            )
            if cursor.rowcount == 0:
                raise ValueError("Active booking not found for this organizer")
            row = connection.execute(
                """
                SELECT id, room_id, organizer, attendees_json, topic, starts_at, ends_at, status
                FROM room_bookings WHERE id = ?
                """,
                (booking_id,),
            ).fetchone()
        return self._booking_from_row(row)

    def list_rooms(self) -> list[RoomSchedule]:
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, room_id, organizer, attendees_json, topic, starts_at, ends_at, status
                FROM room_bookings
                ORDER BY starts_at, id
                """
            ).fetchall()
        bookings = [self._booking_from_row(row) for row in rows]
        return [
            RoomSchedule(
                room=room,
                schedule=[booking for booking in bookings if booking.room_id == room.id],
            )
            for room in ROOMS
        ]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _attendees_json(attendees: tuple[str, ...]) -> str:
        return json.dumps(attendees)

    @staticmethod
    def _booking_from_row(row: sqlite3.Row) -> RoomBooking:
        return RoomBooking(
            id=row["id"],
            room_id=row["room_id"],
            organizer=row["organizer"],
            attendees=tuple(json.loads(row["attendees_json"])),
            topic=row["topic"],
            starts_at=datetime.fromisoformat(row["starts_at"]),
            ends_at=datetime.fromisoformat(row["ends_at"]),
            status=row["status"],
        )
