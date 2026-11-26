import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.events.service import EventService
from backend.events.store import EventStore
from backend.tools.rooms import RoomBookingService


class RunApiTests(unittest.TestCase):
    def test_mock_run_streams_progress_and_final_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events = EventService(EventStore(root / "events.sqlite3", root / "runs"))
            app = create_app(
                events,
                RoomBookingService(root / "rooms.sqlite3"),
                checkpoint_path=root / "checkpoints.sqlite3",
            )
            with patch.dict(os.environ, {"DEV_OFFICE_LLM_PROVIDER": "mock"}, clear=False):
                with TestClient(app) as client:
                    configuration = client.get("/api/agents/config").json()
                    configuration["agents"]["orchestrator"]["name"] = "Coordinator"
                    response = client.post(
                        "/api/runs",
                        json={
                            "prompt": "Build a CSV to JSON tool",
                            "agent_configuration": configuration,
                        },
                    )

                    self.assertEqual(response.status_code, 202)
                    self.assertEqual(response.json()["provider"], "mock")
                    self.assertNotIn("api_key", response.json())
                    self.assertNotIn("GEMINI_API_KEY", response.json())
                    run_id = response.json()["run_id"]
                    replay = client.get(f"/api/runs/{run_id}/events")

            self.assertEqual(replay.status_code, 200)
            event_types = [event["type"] for event in replay.json()]
            self.assertIn("milestone_update", event_types)
            self.assertEqual(event_types[-1], "run_complete")
            orchestrator_events = [
                event for event in replay.json()
                if event["payload"].get("agent_role") == "orchestrator"
            ]
            self.assertTrue(orchestrator_events)
            self.assertTrue(all(event["agent"] == "Coordinator" for event in orchestrator_events))
            milestones = [
                event["payload"]["message"] for event in orchestrator_events
                if event["type"] == "milestone_update"
            ]
            self.assertTrue(any("Coordinator prepared the specification" in message for message in milestones))

    def test_gemini_mode_without_key_returns_setup_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app = create_app(
                EventService(EventStore(root / "events.sqlite3", root / "runs")),
                RoomBookingService(root / "rooms.sqlite3"),
                checkpoint_path=root / "checkpoints.sqlite3",
            )
            with patch.dict(
                os.environ,
                {
                    "DEV_OFFICE_LLM_PROVIDER": "gemini",
                    "GEMINI_API_KEY": "",
                    "GOOGLE_API_KEY": "",
                },
                clear=False,
            ):
                with TestClient(app) as client:
                    response = client.post(
                        "/api/runs",
                        json={"prompt": "Build a CSV to JSON tool"},
                    )

            self.assertEqual(response.status_code, 503)
            self.assertIn("GEMINI_API_KEY", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
