from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.events.service import EventService
from backend.events.store import EventStore
from backend.tools.rooms import BookingConflictError, RoomBookingService


class RoomBookingServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = RoomBookingService(Path(self.temp_dir.name) / "rooms.sqlite3")
        self.start = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def book(self, room_id: str, organizer: str, attendees: list[str], start: datetime | None = None):
        return self.service.book_room(
            room_id=room_id,
            organizer=organizer,
            attendees=attendees,
            topic="Design review",
            duration_minutes=30,
            starts_at=start or self.start,
        )

    def test_prevents_double_booking_room_but_allows_non_overlapping_booking(self) -> None:
        first = self.book("whiteboard_room", "Arjun", ["Maya", "Ojas"])
        with self.assertRaisesRegex(BookingConflictError, "already booked"):
            self.book("whiteboard_room", "Dev", ["Tara"])

        later = self.book(
            "whiteboard_room",
            "Dev",
            ["Tara"],
            self.start + timedelta(minutes=30),
        )
        self.assertEqual(first.room_id, later.room_id)

    def test_prevents_attendee_booking_across_rooms(self) -> None:
        self.book("whiteboard_room", "Arjun", ["Maya", "Ojas"])
        with self.assertRaisesRegex(BookingConflictError, "Maya"):
            self.book("war_room", "Maya", ["Dev"])

    def test_release_frees_room_and_attendees_and_remains_in_schedule(self) -> None:
        booking = self.book("whiteboard_room", "Arjun", ["Maya", "Ojas"])
        released = self.service.release_room(booking.id, "Arjun")
        self.assertEqual(released.status, "released")

        replacement = self.book("whiteboard_room", "Dev", ["Maya"])
        self.assertEqual(replacement.status, "booked")
        schedule = self.service.list_rooms()
        whiteboard = next(room for room in schedule if room.room.id == "whiteboard_room")
        self.assertCountEqual([item.status for item in whiteboard.schedule], ["released", "booked"])

    def test_persists_booking_across_service_instances(self) -> None:
        booking = self.book("focus_room", "Sana", ["Ojas"])
        reopened = RoomBookingService(Path(self.temp_dir.name) / "rooms.sqlite3")
        focus_room = next(room for room in reopened.list_rooms() if room.room.id == "focus_room")
        self.assertEqual(focus_room.schedule, [booking])


class RoomBookingApiTests(unittest.TestCase):
    def test_booking_conflict_schedule_and_release_are_exposed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event_service = EventService(EventStore(root / "events.sqlite3", root / "runs"))
            room_service = RoomBookingService(root / "rooms.sqlite3")
            with TestClient(create_app(event_service, room_service)) as client:
                body = {
                    "organizer": "Arjun",
                    "attendees": ["Maya", "Ojas"],
                    "topic": "Design review",
                    "duration_minutes": 30,
                    "starts_at": "2026-11-18T09:00:00+00:00",
                }
                booked = client.post("/api/rooms/whiteboard_room/bookings", json=body)
                self.assertEqual(booked.status_code, 201)
                self.assertEqual(
                    client.post("/api/rooms/whiteboard_room/bookings", json=body).status_code,
                    409,
                )
                schedule = client.get("/api/rooms").json()
                whiteboard = next(room for room in schedule if room["room"]["id"] == "whiteboard_room")
                self.assertEqual(len(whiteboard["schedule"]), 1)

                released = client.delete(
                    f"/api/rooms/bookings/{booked.json()['id']}?released_by=Arjun"
                )
                self.assertEqual(released.status_code, 200)
                event_types = [
                    event["type"] for event in client.get("/api/runs/office/events").json()
                ]
                self.assertEqual(event_types, ["room_booked", "room_released"])


if __name__ == "__main__":
    unittest.main()
