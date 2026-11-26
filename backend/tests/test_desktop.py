import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QApplication

from backend.desktop import app as desktop_app
from backend.desktop.artifacts import save_run_artifacts
from backend.desktop.dialogs import AgentSettingsDialog
from backend.desktop.worker import GraphWorker
from backend.agents.config import AgentRole, get_default_agent_configuration
from backend.agents.llm_calls import LLMCallObserver
from backend.agents.mock import MockLLM
from backend.events.store import EventStore


class MemorySettings:
    _values: dict[str, str] = {}

    def __init__(self, *args: str) -> None:
        self.organization = args[0] if args else ""
        self.application = args[1] if len(args) > 1 else ""

    def value(self, key: str) -> str | None:
        return type(self)._values.get(key)

    def setValue(self, key: str, value: str) -> None:
        type(self)._values[key] = value


class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])
        desktop_app.register_windows_fonts()

    def setUp(self) -> None:
        MemorySettings._values.clear()

    def test_main_window_refreshes_rooms_and_renders_multiple_bookings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runs_dir = Path(temporary_directory)
            with (
                patch.object(desktop_app, "RUNS_DIR", runs_dir),
                patch.object(desktop_app, "CHECKPOINT_PATH", runs_dir / "checkpoints.sqlite3"),
                patch.object(desktop_app, "QSettings", MemorySettings),
            ):
                window = desktop_app.MainWindow()
                try:
                    window.room_service.book_room(
                        "whiteboard_room",
                        "Maya",
                        ["Arjun"],
                        "Design",
                        20,
                    )
                    window.rooms.set_schedules([])
                    window.rooms.refresh_button.click()
                    whiteboard = window.rooms.schedule.topLevelItem(0)
                    self.assertEqual(whiteboard.childCount(), 1)
                    self.assertEqual(whiteboard.child(0).text(0), "Design")

                    window.room_service.book_room(
                        "war_room",
                        "Dev",
                        ["Tara"],
                        "Testing",
                        20,
                    )
                    window._handle_event(
                        {
                            "run_id": "desktop-ui-run",
                            "type": "room_booked",
                            "agent": "Maya",
                            "room": "Whiteboard Room",
                            "payload": {
                                "topic": "Design",
                                "attendees": ["Maya", "Arjun"],
                                "agent_role": "orchestrator",
                            },
                        }
                    )
                    window._handle_event(
                        {
                            "run_id": "desktop-ui-run",
                            "type": "room_booked",
                            "agent": "Dev",
                            "room": "War Room",
                            "payload": {
                                "topic": "Testing",
                                "attendees": ["Dev", "Tara"],
                                "agent_role": "developer",
                            },
                        }
                    )
                    self.assertEqual(
                        window.office.bookings,
                        {
                            "whiteboard_room": {"Maya", "Arjun"},
                            "war_room": {"Dev", "Tara"},
                        },
                    )

                    window.office.resize(880, 510)
                    image = QImage(880, 510, QImage.Format.Format_ARGB32)
                    painter = QPainter(image)
                    window.office.render(painter)
                    painter.end()
                    self.assertFalse(image.isNull())
                finally:
                    window.close()
                    window.deleteLater()
                    self.application.processEvents()

    def test_agent_settings_dialog_accepts_customized_configuration(self) -> None:
        defaults = get_default_agent_configuration()
        dialog = AgentSettingsDialog(defaults, defaults)
        dialog._fields["orchestrator"][0].setText("Maya Updated")

        dialog._save_and_accept()

        self.assertEqual(
            dialog.agent_configuration.agents[AgentRole.ORCHESTRATOR].name,
            "Maya Updated",
        )
        self.assertEqual(dialog.agent_list.count(), 7)

    def test_sample_run_replays_events_and_can_pause_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with (
                patch.object(desktop_app, "RUNS_DIR", root),
                patch.object(desktop_app, "CHECKPOINT_PATH", root / "checkpoints.sqlite3"),
                patch.object(desktop_app, "QSettings", MemorySettings),
            ):
                window = desktop_app.MainWindow()
                try:
                    self.assertEqual(window.speed.currentData(), 1.0)
                    window._start_demo()
                    self.assertTrue(window._demo_running)
                    window._toggle_demo()
                    self.assertFalse(window.demo_timer.isActive())
                    window._toggle_demo()
                    self.assertTrue(window.demo_timer.isActive())

                    window.demo_timer.stop()
                    window._play_next_demo_event()
                    window._play_next_demo_event()
                    window._play_next_demo_event()
                    self.assertEqual(window.events[-1]["type"], "room_booked")
                    self.assertNotEqual(
                        window.office.targets["orchestrator"].y(),
                        window.office.positions["orchestrator"].y(),
                    )

                    while window._demo_cursor < len(desktop_app.DEMO_EVENTS):
                        window.demo_timer.stop()
                        window._play_next_demo_event()
                    window.demo_timer.stop()
                    window._play_next_demo_event()
                    self.assertFalse(window._demo_running)
                    self.assertEqual(window.progress.value(), 100)
                    self.assertGreater(window.updates.count(), 0)
                    self.assertGreater(window.transcript.count(), 0)
                finally:
                    window._stop_demo()
                    window.close()
                    window.deleteLater()
                    self.application.processEvents()

    def test_artifact_zip_contains_generated_files_and_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            projects_root = Path(temporary_directory) / "projects"
            with patch.object(desktop_app, "PROJECTS_DIR", projects_root):
                project_path = desktop_app.MainWindow._project_directory_for(
                    r"..\..\unsafe: csv converter",
                    "run-safe",
                )
            self.assertEqual(project_path.parent, projects_root)
            self.assertTrue(project_path.name.endswith("-run-safe"))

            run_directory = Path(temporary_directory) / "run"
            project_directory = projects_root / "csv-converter-run"
            archive_path = save_run_artifacts(
                run_directory,
                {
                    "spec": {"goals": ["Build a tool"]},
                    "implementation": {"files": {"src/tool.py": "print('not run')"}},
                    "final_acceptance": {"status": "completed"},
                },
                project_directory=project_directory,
            )
            self.assertEqual(
                (project_directory / "src" / "tool.py").read_text(encoding="utf-8"),
                "print('not run')",
            )
            self.assertTrue((run_directory / "workspace" / "src" / "tool.py").is_file())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("src/tool.py", archive.namelist())
                self.assertIn(".devoffice/spec.json", archive.namelist())

            with self.assertRaisesRegex(ValueError, "safe relative path"):
                save_run_artifacts(
                    Path(temporary_directory) / "unsafe-run",
                    {"implementation": {"files": {"../outside.txt": "unsafe"}}},
                )
            self.assertFalse((Path(temporary_directory) / "outside.txt").exists())

    def test_graph_worker_persists_events_and_resumes_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            event_store = EventStore(root / "events.sqlite3", root)
            runtime_selections: list[tuple[str | None, str | None]] = []

            def create_mock_runtime(
                provider: str | None,
                *,
                model_name: str | None,
                on_llm_call: LLMCallObserver | None,
            ) -> MockLLM:
                runtime_selections.append((provider, model_name))
                return MockLLM(on_llm_call=on_llm_call)

            worker = GraphWorker(
                "desktop-approval-run",
                "Build a CSV to JSON converter.",
                True,
                get_default_agent_configuration(),
                root / "checkpoints.sqlite3",
                event_store,
                model_name="desktop-selected-model",
            )
            approvals: list[dict[str, object]] = []
            completions: list[dict[str, object]] = []
            failures: list[str] = []
            worker.approval_requested.connect(approvals.append)
            worker.run_completed.connect(completions.append)
            worker.run_failed.connect(failures.append)

            with patch(
                "backend.desktop.worker.create_agent_runtime",
                side_effect=create_mock_runtime,
            ):
                worker.run()
                self.assertEqual(len(approvals), 1)
                self.assertFalse(completions)
                worker.resume_approval(True)

            self.assertFalse(failures)
            self.assertEqual(runtime_selections, [(None, "desktop-selected-model")])
            self.assertEqual(completions[0]["final_acceptance"]["status"], "completed")
            stored_events = event_store.replay("desktop-approval-run")
            self.assertIn("run_complete", [event.type.value for event in stored_events])
            call_log = root / "desktop-approval-run" / "llm_calls.jsonl"
            calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(calls)
            self.assertTrue(all(call["run_id"] == "desktop-approval-run" for call in calls))
            self.assertTrue(all(call["provider"] == "mock" for call in calls))
            self.assertNotIn("api_key", json.dumps(calls).lower())

    def test_run_completion_saves_project_to_projects_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            projects_root = root / "projects"
            with (
                patch.object(desktop_app, "RUNS_DIR", root / "runs"),
                patch.object(desktop_app, "CHECKPOINT_PATH", root / "runs" / "checkpoints.sqlite3"),
                patch.object(desktop_app, "PROJECTS_DIR", projects_root),
                patch.object(desktop_app, "QSettings", MemorySettings),
            ):
                window = desktop_app.MainWindow()
                try:
                    window.current_run_id = "project-output-run"
                    project_directory = projects_root / "csv-json-project-output-run"
                    window.current_project_directory = project_directory
                    window._set_project_title("Build a CSV to JSON tool")
                    window._run_completed(
                        {
                            "implementation": {"files": {"src/tool.py": "print('ready')"}},
                            "final_acceptance": {
                                "status": "completed",
                                "summary": "Ready.",
                            },
                        }
                    )
                    self.assertTrue(
                        (project_directory / "src" / "tool.py").is_file()
                    )
                    self.assertTrue(window.deliverable_path and window.deliverable_path.is_file())
                    self.assertIn(str(projects_root), window.project_subtitle_label.text())
                finally:
                    window.close()
                    window.deleteLater()
                    self.application.processEvents()

    def test_settings_persist_agent_model_and_animation_across_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            settings_patch = (
                patch.object(desktop_app, "RUNS_DIR", root),
                patch.object(desktop_app, "CHECKPOINT_PATH", root / "checkpoints.sqlite3"),
                patch.object(desktop_app, "PROJECTS_DIR", root / "projects"),
                patch.object(desktop_app, "QSettings", MemorySettings),
            )
            with settings_patch[0], settings_patch[1], settings_patch[2], settings_patch[3]:
                first = desktop_app.MainWindow()
                try:
                    first.agent_editor._fields["orchestrator"][0].setText("Maya Future")
                    first.agent_editor._fields["developer"][2].setPlainText(
                        "Keep this task prompt for all later runs."
                    )
                    first.agent_editor.save_button.click()
                    first.model_combo.setCurrentText("gemini-2.5-flash")
                    first._save_model()
                    first.speed.setCurrentIndex(2)
                finally:
                    first.close()
                    first.deleteLater()
                    self.application.processEvents()

                second = desktop_app.MainWindow()
                try:
                    self.assertEqual(
                        second.agent_configuration.agents[AgentRole.ORCHESTRATOR].name,
                        "Maya Future",
                    )
                    self.assertEqual(
                        second.agent_configuration.agents[AgentRole.DEVELOPER].task_prompt,
                        "Keep this task prompt for all later runs.",
                    )
                    self.assertEqual(second.model_name, "gemini-2.5-flash")
                    self.assertEqual(second.speed.currentData(), 2.0)
                    self.assertEqual(second.settings_tabs.tabText(0), "Agents")
                    self.assertEqual(second.settings_tabs.tabText(1), "Animation")
                    self.assertEqual(second.settings_tabs.tabText(2), "LLM Model")
                finally:
                    second.close()
                    second.deleteLater()
                    self.application.processEvents()

    def test_main_dashboard_updates_design_plan_canvas_and_llm_console(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with (
                patch.object(desktop_app, "RUNS_DIR", root),
                patch.object(desktop_app, "CHECKPOINT_PATH", root / "checkpoints.sqlite3"),
                patch.object(desktop_app, "PROJECTS_DIR", root / "projects"),
                patch.object(desktop_app, "QSettings", MemorySettings),
            ):
                window = desktop_app.MainWindow()
                try:
                    window._handle_event(
                        {
                            "run_id": "dashboard-run",
                            "type": "artifact_created",
                            "agent": "Arjun",
                            "payload": {
                                "artifact": "design",
                                "components": ["CSV reader", "Schema validator"],
                                "dependencies": ["Python standard library"],
                                "file_tree": ["src/main.py"],
                            },
                        }
                    )
                    self.assertEqual(window.tech_stack.item(0).text(), "Python standard library")
                    self.assertEqual(window.build_canvas.components[0], "CSV reader")

                    window._handle_event(
                        {
                            "run_id": "dashboard-run",
                            "type": "milestone_update",
                            "agent": "Maya",
                            "payload": {
                                "stage": "3 of 8",
                                "status": "in_progress",
                                "message": "Design review is underway.",
                            },
                        }
                    )
                    self.assertEqual(window.progress.value(), 38)
                    self.assertIn("Review and approve", window.plan_list.item(2).text())

                    window.llm_console.add_call(
                        {
                            "id": "live-call",
                            "phase": "request",
                            "role": "architect",
                            "model": "gemini-test",
                            "attempt": 1,
                            "status": "pending",
                            "request": {"human": "design this"},
                            "response": None,
                        }
                    )
                    window.llm_console.add_call(
                        {
                            "id": "live-call",
                            "phase": "response",
                            "role": "architect",
                            "model": "gemini-test",
                            "attempt": 1,
                            "status": "success",
                            "request": {"human": "design this"},
                            "response": {"components": ["CSV reader"]},
                        }
                    )
                    self.assertIn("design this", window.llm_console.request.toPlainText())
                    self.assertIn("CSV reader", window.llm_console.response.toPlainText())
                    self.assertEqual(window.llm_console.calls.count(), 1)
                    self.assertEqual(window.main_tabs.tabText(0), "Main")
                    self.assertEqual(window.main_tabs.tabText(1), "LLM Console")
                    self.assertEqual(window.main_tabs.tabText(2), "Settings")

                    window.build_canvas.resize(860, 460)
                    image = QImage(860, 460, QImage.Format.Format_ARGB32)
                    painter = QPainter(image)
                    window.build_canvas.render(painter)
                    painter.end()
                    self.assertFalse(image.isNull())
                finally:
                    window.close()
                    window.deleteLater()
                    self.application.processEvents()


if __name__ == "__main__":
    unittest.main()
