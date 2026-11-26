import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.events.schema import EventEnvelope, EventType
from backend.events.service import EventService
from backend.events.store import EventStore


class EventStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.runs_dir = root / "runs"
        self.store = EventStore(root / "events.sqlite3", self.runs_dir)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_persists_run_log_and_replays_after_cursor(self) -> None:
        first = EventEnvelope(run_id="run_1", type=EventType.AGENT_STATUS, agent="Maya")
        second = EventEnvelope(run_id="run_1", type=EventType.MILESTONE_UPDATE, payload={"stage": 1})
        other_run = EventEnvelope(run_id="run_2", type=EventType.ERROR)
        self.store.append(first)
        self.store.append(second)
        self.store.append(other_run)

        self.assertEqual(self.store.replay("run_1", first.id), [second])
        log_lines = (self.runs_dir / "run_1" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["id"] for line in log_lines], [first.id, second.id])

    def test_rejects_cursor_from_another_run(self) -> None:
        event = EventEnvelope(run_id="run_1", type=EventType.ERROR)
        self.store.append(event)
        with self.assertRaisesRegex(ValueError, "not found"):
            self.store.replay("run_2", event.id)


class EventApiTests(unittest.TestCase):
    def test_websocket_replays_and_streams_typed_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = EventService(EventStore(root / "events.sqlite3", root / "runs"))
            previous = EventEnvelope(
                run_id="demo-run",
                type=EventType.AGENT_STATUS,
                agent="Maya",
                payload={"status": "working"},
            )
            service.store.append(previous)
            client = TestClient(create_app(service))
            with client:
                with client.websocket_connect("/ws/demo-run") as websocket:
                    replayed = websocket.receive_json()
                    self.assertEqual(replayed["id"], previous.id)
                    response = client.post(
                        "/api/runs/demo-run/events",
                        json={
                            "type": "milestone_update",
                            "agent": "Maya",
                            "payload": {"message": "Spec ready"},
                        },
                    )
                    self.assertEqual(response.status_code, 201)
                    received = websocket.receive_json()
                    self.assertEqual(received["id"], response.json()["id"])
                    self.assertEqual(received["type"], "milestone_update")
                    self.assertEqual(received["run_id"], "demo-run")

            replay = client.get("/api/runs/demo-run/events")
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(len(replay.json()), 2)
            self.assertEqual(replay.json()[1]["payload"]["message"], "Spec ready")


if __name__ == "__main__":
    unittest.main()
