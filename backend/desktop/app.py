import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import ValidationError
from PyQt6.QtCore import Qt, QSettings, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QFontDatabase
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from backend.agents.config import (
    AgentConfiguration,
    AgentRole,
    get_default_agent_configuration,
)
from backend.agents.runtime import DEFAULT_GEMINI_MODEL
from backend.desktop.canvas import BuildCanvasWidget
from backend.desktop.artifacts import save_run_artifacts
from backend.desktop.dialogs import AgentSettingsEditor, BookingDialog
from backend.desktop.office import AGENT_COLORS, OfficeWidget
from backend.desktop.worker import GraphWorker
from backend.events.schema import EventEnvelope, EventType
from backend.events.store import EventStore
from backend.tools.rooms import (
    BookingConflictError,
    ROOM_BY_ID,
    RoomBookingService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)
RUNS_DIR = Path(os.environ.get("DEV_OFFICE_RUNS_DIR", PROJECT_ROOT / "runs")).resolve()
PROJECTS_DIR = PROJECT_ROOT / "projects"
CHECKPOINT_PATH = RUNS_DIR / "checkpoints.sqlite3"
SETTINGS_KEY = "agents/configuration"
MODEL_SETTINGS_KEY = "llm/model"
ANIMATION_SETTINGS_KEY = "animation/speed"
LOGGER = logging.getLogger(__name__)
DEMO_RUN_ID = "mock-csv-demo"
DEMO_EVENTS: tuple[tuple[str, str, str | None, dict[str, Any]], ...] = (
    ("agent_status", "Maya", None, {"agent_role": "orchestrator", "activity": "turning the prompt into a spec"}),
    ("milestone_update", "Maya", None, {"agent_role": "orchestrator", "stage": "1 of 8", "status": "in_progress", "message": "Maya prepared the specification. Arjun is starting the design.", "risks": []}),
    ("room_booked", "Maya", "Whiteboard Room", {"agent_role": "orchestrator", "topic": "Kickoff", "attendees": ["Maya", "Arjun", "Dev", "Sana", "Tara", "Doc", "Ojas"]}),
    ("meeting_started", "Maya", "Whiteboard Room", {"agent_role": "orchestrator", "topic": "Kickoff", "goal": "Align on the CSV-to-JSON tool"}),
    ("meeting_message", "Maya", "Whiteboard Room", {"agent_role": "orchestrator", "text": "Let’s make invalid rows clear, and never leave a half-written JSON file."}),
    ("meeting_message", "Arjun", "Whiteboard Room", {"agent_role": "architect", "text": "A small parser, validator, and writer should be enough. No framework needed."}),
    ("meeting_ended", "Maya", "Whiteboard Room", {"agent_role": "orchestrator", "decisions": ["Validate before writing output"], "action_items": ["Arjun to finish the design"], "blockers": []}),
    ("room_released", "Maya", "Whiteboard Room", {"agent_role": "orchestrator"}),
    ("artifact_created", "Arjun", None, {"agent_role": "architect", "artifact": "design", "title": "Technical design", "components": ["CLI argument parser", "CSV reader", "Schema validator"], "dependencies": ["Python standard library"], "file_tree": ["src/main.py", "src/converter.py", "tests/test_converter.py"]}),
    ("room_booked", "Arjun", "War Room", {"agent_role": "architect", "topic": "Design Review", "attendees": ["Arjun", "Sana", "Ojas", "Maya"]}),
    ("meeting_started", "Arjun", "War Room", {"agent_role": "architect", "topic": "Design Review", "goal": "Approve the components and threat model"}),
    ("meeting_message", "Sana", "War Room", {"agent_role": "cyber_security", "text": "Reject malformed schemas before opening or writing the output file."}),
    ("meeting_message", "Ojas", "War Room", {"agent_role": "critic", "text": "Good. Make the invalid-row behavior explicit, not a footnote."}),
    ("review_verdict", "Ojas", None, {"agent_role": "critic", "phase": "design", "verdict": "APPROVE", "comments": []}),
    ("security_finding", "Sana", None, {"agent_role": "cyber_security", "phase": "design", "gate": "PASS", "finding": None}),
    ("meeting_ended", "Arjun", "War Room", {"agent_role": "architect", "decisions": ["Design approved"], "action_items": ["Dev to begin implementation"], "blockers": []}),
    ("room_released", "Arjun", "War Room", {"agent_role": "architect"}),
    ("milestone_update", "Maya", None, {"agent_role": "orchestrator", "stage": "3 of 8", "status": "in_progress", "message": "The design passed review. Dev is starting the implementation.", "risks": []}),
    ("agent_status", "Dev", None, {"agent_role": "developer", "activity": "implementing the approved design"}),
    ("artifact_created", "Dev", None, {"agent_role": "developer", "artifact": "code", "title": "Implementation", "files": ["src/main.py", "src/converter.py", "tests/test_converter.py"], "summary": "The CLI, converter, and tests are ready for review."}),
    ("milestone_update", "Maya", None, {"agent_role": "orchestrator", "stage": "4 of 8", "status": "in_progress", "message": "Dev prepared the implementation. Tara, Sana, and Ojas are reviewing it now.", "risks": []}),
    ("room_booked", "Dev", "Focus Room", {"agent_role": "developer", "topic": "Code Review", "attendees": ["Dev", "Ojas", "Sana", "Tara"]}),
    ("meeting_started", "Dev", "Focus Room", {"agent_role": "developer", "topic": "Code Review", "goal": "Review implementation, tests, and security"}),
    ("test_result", "Tara", None, {"agent_role": "tester", "passed": 4, "failed": 0, "failing_cases": []}),
    ("security_finding", "Sana", None, {"agent_role": "cyber_security", "phase": "code", "gate": "PASS", "finding": None}),
    ("review_verdict", "Ojas", None, {"agent_role": "critic", "phase": "code", "verdict": "APPROVE", "comments": []}),
    ("meeting_message", "Ojas", "Focus Room", {"agent_role": "critic", "text": "Scoped, readable, and the acceptance path is covered. Ship it."}),
    ("meeting_ended", "Dev", "Focus Room", {"agent_role": "developer", "decisions": ["Approve for documentation"], "action_items": ["Doc to write usage notes"], "blockers": []}),
    ("room_released", "Dev", "Focus Room", {"agent_role": "developer"}),
    ("artifact_created", "Doc", None, {"agent_role": "documentation", "artifact": "documentation", "title": "Usage documentation"}),
    ("milestone_update", "Maya", None, {"agent_role": "orchestrator", "stage": "7 of 8", "status": "in_progress", "message": "Doc finished the usage notes. Maya is checking final acceptance.", "risks": []}),
    ("milestone_update", "Maya", None, {"agent_role": "orchestrator", "stage": "8 of 8", "status": "completed", "message": "The run passed its review gates. The CSV-to-JSON tool is ready.", "risks": []}),
    ("run_complete", "Maya", None, {"agent_role": "orchestrator", "accepted": True, "status": "completed", "known_issues": [], "summary": "The run passed its configured mock acceptance gates."}),
)


def register_windows_fonts() -> None:
    if os.name != "nt":
        return
    windows_directory = Path(os.environ.get("WINDIR", r"C:\Windows"))
    font_directory = windows_directory / "Fonts"
    for filename in ("segoeui.ttf", "georgia.ttf"):
        font_path = font_directory / filename
        if not font_path.is_file():
            continue
        if QFontDatabase.addApplicationFont(str(font_path)) < 0:
            LOGGER.warning("Could not register installed UI font: %s", font_path.name)


class RoomsTab(QWidget):
    book_requested = pyqtSignal()
    release_requested = pyqtSignal(str, str)
    refresh_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.schedule = QTreeWidget()
        self.schedule.setColumnCount(4)
        self.schedule.setHeaderLabels(["Room / topic", "Organizer", "Starts", "Status"])
        self.schedule.setAlternatingRowColors(True)
        layout.addWidget(self.schedule)

        controls = QHBoxLayout()
        self.book_button = QPushButton("Book a room")
        self.release_button = QPushButton("Release selected")
        self.refresh_button = QPushButton("Refresh")
        self.release_button.setEnabled(False)
        controls.addWidget(self.book_button)
        controls.addWidget(self.release_button)
        controls.addStretch(1)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)
        self.book_button.clicked.connect(self.book_requested.emit)
        self.release_button.clicked.connect(self._release_selected)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.schedule.currentItemChanged.connect(self._selection_changed)

    def set_schedules(self, schedules: list[Any]) -> None:
        self.schedule.clear()
        for room_schedule in schedules:
            room_item = QTreeWidgetItem([room_schedule.room.name, "", "", ""])
            room_item.setData(0, Qt.ItemDataRole.UserRole, None)
            self.schedule.addTopLevelItem(room_item)
            for booking in room_schedule.schedule:
                status = "Booked" if booking.status == "booked" else "Released"
                row = QTreeWidgetItem(
                    [
                        booking.topic,
                        booking.organizer,
                        booking.starts_at.astimezone().strftime("%b %d, %I:%M %p"),
                        status,
                    ]
                )
                row.setData(0, Qt.ItemDataRole.UserRole, booking.id)
                row.setData(1, Qt.ItemDataRole.UserRole, booking.organizer)
                room_item.addChild(row)
            room_item.setExpanded(True)
        self.schedule.resizeColumnToContents(0)

    def _selection_changed(self, current: QTreeWidgetItem | None) -> None:
        self.release_button.setEnabled(
            current is not None
            and bool(current.data(0, Qt.ItemDataRole.UserRole))
            and current.text(3) == "Booked"
        )

    def _release_selected(self) -> None:
        current = self.schedule.currentItem()
        if current is None:
            return
        booking_id = current.data(0, Qt.ItemDataRole.UserRole)
        organizer = current.data(1, Qt.ItemDataRole.UserRole)
        if booking_id and organizer:
            self.release_requested.emit(str(booking_id), str(organizer))


class ArtifactTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Run artifacts")
        self.preview = QTextBrowser()
        self.preview.setOpenExternalLinks(False)
        self.splitter.addWidget(self.tree)
        self.splitter.addWidget(self.preview)
        self.splitter.setSizes([230, 300])
        layout.addWidget(self.splitter)
        self.tree.currentItemChanged.connect(self._show_item)

    def set_result(self, result: dict[str, Any]) -> None:
        self.tree.clear()
        for key in (
            "spec",
            "design",
            "implementation",
            "design_security_report",
            "design_critic_report",
            "security_report",
            "critic_report",
            "test_report",
            "documentation",
            "final_acceptance",
        ):
            if key not in result:
                continue
            value = result[key]
            title = key.replace("_", " ").title()
            parent = QTreeWidgetItem([title])
            self.tree.addTopLevelItem(parent)
            if isinstance(value, dict) and isinstance(value.get("files"), dict):
                summary = value.get("summary", "")
                if summary:
                    summary_item = QTreeWidgetItem(["Summary"])
                    summary_item.setData(0, Qt.ItemDataRole.UserRole, str(summary))
                    parent.addChild(summary_item)
                for path, contents in value["files"].items():
                    item = QTreeWidgetItem([str(path)])
                    item.setData(0, Qt.ItemDataRole.UserRole, str(contents))
                    parent.addChild(item)
            else:
                child = QTreeWidgetItem(["View report"])
                child.setData(0, Qt.ItemDataRole.UserRole, json.dumps(value, ensure_ascii=False, indent=2))
                parent.addChild(child)
            parent.setExpanded(True)
        self.tree.resizeColumnToContents(0)
        self.preview.setPlainText("Select an artifact to preview it.")

    def _show_item(self, current: QTreeWidgetItem | None) -> None:
        if current is None:
            self.preview.clear()
            return
        value = current.data(0, Qt.ItemDataRole.UserRole)
        self.preview.setPlainText(str(value) if value is not None else current.text(0))


class LLMConsoleTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Gemini entries show the exact prompts and structured response. Mock entries show local context only "
            "(no API request is made). Calls are saved with the run."
        )
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.calls = QListWidget()
        self.calls.setMinimumWidth(210)
        self.calls.currentRowChanged.connect(self._show_call)
        splitter.addWidget(self.calls)

        self.details = QTabWidget()
        self.request = QPlainTextEdit()
        self.request.setReadOnly(True)
        self.response = QPlainTextEdit()
        self.response.setReadOnly(True)
        self.details.addTab(self.request, "Request")
        self.details.addTab(self.response, "Response")
        splitter.addWidget(self.details)
        splitter.setSizes([280, 880])
        layout.addWidget(splitter, 1)
        self.clear_calls()

    def clear_calls(self) -> None:
        self._records: list[dict[str, Any]] = []
        self._record_indexes: dict[str, int] = {}
        self.calls.clear()
        self.request.setPlainText("No model calls yet. Start a run to see its live requests.")
        self.response.clear()

    def set_records(self, records: list[dict[str, Any]]) -> None:
        self.clear_calls()
        for record in records:
            self.add_call(record)

    def add_call(self, record: dict[str, Any]) -> None:
        call_id = str(record.get("id", ""))
        index = self._record_indexes.get(call_id) if call_id else None
        is_new = index is None
        if index is None:
            index = len(self._records)
            self._records.append(record)
            if call_id:
                self._record_indexes[call_id] = index
            self.calls.addItem("")
        else:
            self._records[index] = record
        timestamp = ""
        try:
            timestamp = datetime.fromisoformat(str(record.get("ts"))).astimezone().strftime("%H:%M:%S")
        except ValueError:
            pass
        role = str(record.get("role", "agent")).replace("_", " ").title()
        attempt = record.get("attempt", 1)
        status = str(record.get("status", "sent")).replace("_", " ")
        model = record.get("model", "unknown model")
        time_prefix = f"{timestamp} · " if timestamp else ""
        self.calls.item(index).setText(
            f"{time_prefix}{role} · try {attempt} · {status}\n{model}"
        )
        if is_new or self.calls.currentRow() < 0:
            self.calls.setCurrentRow(index)
        if self.calls.currentRow() == index:
            self._show_call(index)

    def _show_call(self, index: int) -> None:
        if index < 0 or index >= len(self._records):
            return
        record = self._records[index]
        self.request.setPlainText(
            json.dumps(record.get("request", {}), ensure_ascii=False, indent=2)
        )
        self.response.setPlainText(
            json.dumps(
                {
                    "phase": record.get("phase"),
                    "provider": record.get("provider"),
                    "model": record.get("model"),
                    "status": record.get("status"),
                    "duration_ms": record.get("duration_ms"),
                    "response": record.get("response"),
                    "error": record.get("error"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


class MainWindow(QMainWindow):
    approval_decision = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DevOffice · Multi-agent team")
        self.resize(1500, 960)
        self.setMinimumSize(980, 680)
        self.runs_dir = RUNS_DIR
        self.event_store = EventStore(self.runs_dir / "events.sqlite3", self.runs_dir)
        self.room_service = RoomBookingService(self.runs_dir / "rooms.sqlite3")
        self.defaults = get_default_agent_configuration()
        self.settings = QSettings("DevOffice", "DevOffice")
        self.agent_configuration = self._load_agent_configuration()
        stored_model = self.settings.value(MODEL_SETTINGS_KEY)
        self.model_name = str(
            stored_model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        ).strip()
        if not self.model_name:
            self.model_name = DEFAULT_GEMINI_MODEL
        self.current_run_id: str | None = None
        self.current_project_directory: Path | None = None
        self.events: list[dict[str, Any]] = []
        self.last_result: dict[str, Any] | None = None
        self.deliverable_path: Path | None = None
        self._thread: QThread | None = None
        self._worker: GraphWorker | None = None
        self._agent_activities: dict[str, str] = {}
        self._event_count = 0
        self._demo_cursor = 0
        self._demo_running = False

        self._build_ui()
        self._apply_theme()
        self._select_agent(AgentRole.ORCHESTRATOR.value)
        self._refresh_rooms()
        self._refresh_history()
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.office.tick)
        self.animation_timer.start(30)
        self.demo_timer = QTimer(self)
        self.demo_timer.timeout.connect(self._play_next_demo_event)

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 12, 28, 18)
        root.setSpacing(14)
        self.setCentralWidget(central)

        header = QHBoxLayout()
        brand = QHBoxLayout()
        brand_mark = QLabel("D")
        brand_mark.setObjectName("brandMark")
        brand_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(brand_mark)
        brand_text = QVBoxLayout()
        brand_title = QLabel("DevOffice")
        brand_title.setObjectName("brandTitle")
        brand_subtitle = QLabel("A small team, at work")
        brand_subtitle.setObjectName("muted")
        brand_text.addWidget(brand_title)
        brand_text.addWidget(brand_subtitle)
        brand.addLayout(brand_text)
        header.addLayout(brand)
        header.addStretch(1)
        self.provider_label = QLabel("READY")
        self.provider_label.setObjectName("provider")
        header.addWidget(self.provider_label)
        self.run_id_label = QLabel("Ready for a new build")
        self.run_id_label.setObjectName("runId")
        header.addWidget(self.run_id_label)
        header.addWidget(QLabel("Run history"))
        self.history = QComboBox()
        self.history.setMinimumWidth(150)
        self.history.currentIndexChanged.connect(self._history_selected)
        header.addWidget(self.history)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.setEnabled(False)
        self.pause_button.setVisible(False)
        self.pause_button.clicked.connect(self._toggle_demo)
        header.addWidget(self.pause_button)
        self.demo_button = QPushButton("Watch demo")
        self.demo_button.clicked.connect(self._start_demo)
        header.addWidget(self.demo_button)
        root.addLayout(header)

        self.main_tabs = QTabWidget()
        main_page = QWidget()
        main_page_layout = QVBoxLayout(main_page)
        main_page_layout.setContentsMargins(0, 0, 0, 0)
        main_page_layout.setSpacing(10)

        columns = QSplitter(Qt.Orientation.Horizontal)
        main_page_layout.addWidget(columns, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        request_frame = QFrame()
        request_frame.setObjectName("card")
        request_layout = QVBoxLayout(request_frame)
        request_layout.setContentsMargins(17, 13, 17, 11)
        request_layout.setSpacing(7)
        request_layout.addWidget(QLabel("What should the team make?"))
        request_row = QHBoxLayout()
        request_row.setSpacing(9)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText("Describe the tool you have in mind…")
        self.prompt.setMaximumBlockCount(2000)
        self.prompt.setPlainText(
            "Build a CLI tool that converts CSV files to JSON with schema validation."
        )
        self.prompt.setFixedHeight(64)
        request_row.addWidget(self.prompt, 1)
        self.run_button = QPushButton("Build with configured LLM")
        self.run_button.setObjectName("primaryButton")
        self.run_button.setMinimumWidth(190)
        self.run_button.clicked.connect(self._start_run)
        request_row.addWidget(self.run_button)
        request_layout.addLayout(request_row)
        run_controls = QHBoxLayout()
        self.approval_checkbox = QCheckBox("Require spec approval")
        run_controls.addWidget(self.approval_checkbox)
        run_controls.addStretch(1)
        self.request_note = QLabel("Real runs use the configured model. The sample run works without an API key.")
        self.request_note.setObjectName("footnote")
        run_controls.addWidget(self.request_note)
        self.sample_run_button = QPushButton("Play the sample run")
        self.sample_run_button.setObjectName("textButton")
        self.sample_run_button.clicked.connect(self._start_demo)
        run_controls.addWidget(self.sample_run_button)
        request_layout.addLayout(run_controls)
        left_layout.addWidget(request_frame)

        project_frame = QFrame()
        project_frame.setObjectName("card")
        project_layout = QHBoxLayout(project_frame)
        project_layout.setContentsMargins(20, 13, 20, 13)
        project_copy = QVBoxLayout()
        project_copy.setSpacing(2)
        project_kicker = QLabel("TODAY'S BUILD")
        project_kicker.setObjectName("sectionKicker")
        self.project_title_label = QLabel("A CSV to JSON tool")
        self.project_title_label.setObjectName("projectTitle")
        project_subtitle = QLabel("With schema validation, just as requested.")
        self.project_subtitle_label = project_subtitle
        project_subtitle.setObjectName("muted")
        project_subtitle.setWordWrap(True)
        project_copy.addWidget(project_kicker)
        project_copy.addWidget(self.project_title_label)
        project_copy.addWidget(project_subtitle)
        project_layout.addLayout(project_copy, 1)
        progress_column = QVBoxLayout()
        progress_caption = QHBoxLayout()
        progress_caption.addWidget(QLabel("Team progress"))
        self.progress_label = QLabel("Getting started")
        self.progress_label.setObjectName("progressLabel")
        progress_caption.addWidget(self.progress_label, 0, Qt.AlignmentFlag.AlignRight)
        progress_column.addLayout(progress_caption)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        progress_column.addWidget(self.progress)
        project_layout.addLayout(progress_column, 1)
        left_layout.addWidget(project_frame)

        floor_frame = QFrame()
        floor_frame.setObjectName("officeCard")
        floor_layout = QVBoxLayout(floor_frame)
        floor_layout.setContentsMargins(0, 0, 0, 0)
        floor_layout.setSpacing(0)
        floor_header = QHBoxLayout()
        floor_header.setContentsMargins(18, 9, 18, 9)
        floor_heading = QVBoxLayout()
        floor_heading.setSpacing(1)
        floor_kicker = QLabel("THE FLOOR")
        floor_kicker.setObjectName("sectionKicker")
        floor_date = QLabel(datetime.now().strftime("%A, %b %d at DevOffice"))
        floor_date.setObjectName("floorDate")
        floor_heading.addWidget(floor_kicker)
        floor_heading.addWidget(floor_date)
        floor_header.addLayout(floor_heading)
        floor_header.addStretch(1)
        self.floor_status = QLabel("Everyone at their desks")
        self.floor_status.setObjectName("floorStatus")
        floor_header.addWidget(self.floor_status)
        floor_layout.addLayout(floor_header)
        self.office = OfficeWidget(self.agent_configuration)
        self.office.agent_selected.connect(self._select_agent)
        self.build_canvas = BuildCanvasWidget()
        self.canvas_tabs = QTabWidget()
        self.canvas_tabs.addTab(self.office, "Office floor")
        self.canvas_tabs.addTab(self.build_canvas, "Build canvas")
        floor_layout.addWidget(self.canvas_tabs, 1)
        left_layout.addWidget(floor_frame, 1)

        self.agent_card = QFrame()
        self.agent_card.setObjectName("card")
        agent_layout = QHBoxLayout(self.agent_card)
        agent_layout.setContentsMargins(14, 9, 14, 9)
        self.agent_avatar = QLabel("M")
        self.agent_avatar.setObjectName("agentAvatar")
        self.agent_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.agent_avatar.setFixedSize(42, 42)
        agent_layout.addWidget(self.agent_avatar)
        agent_text = QVBoxLayout()
        agent_text.setSpacing(2)
        self.agent_name = QLabel()
        self.agent_name.setObjectName("agentName")
        self.agent_activity = QLabel()
        self.agent_activity.setObjectName("agentActivity")
        agent_text.addWidget(self.agent_name)
        agent_text.addWidget(self.agent_activity)
        agent_layout.addLayout(agent_text, 1)
        self.latest_artifact_label = QLabel()
        self.latest_artifact_label.setObjectName("artifactBadge")
        self.latest_artifact_label.setVisible(False)
        agent_layout.addWidget(self.latest_artifact_label)
        left_layout.addWidget(self.agent_card)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setWidget(left)
        columns.addWidget(left_scroll)

        self.panels = QTabWidget()
        self.updates = QListWidget()
        self.updates.setObjectName("feedList")
        self.updates.setWordWrap(True)
        self.updates.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.updates.addItem("Maya will leave a note when the team reaches a milestone.")
        self.transcript = QListWidget()
        self.transcript.setObjectName("feedList")
        self.transcript.setWordWrap(True)
        self.transcript.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.transcript.addItem("Pull up a chair. The first meeting will show up here.")
        self.artifacts = ArtifactTab()
        self.rooms = RoomsTab()
        self.live_dashboard = self._build_live_dashboard()
        self.live_scroll = QScrollArea()
        self.live_scroll.setWidgetResizable(True)
        self.live_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.live_scroll.setWidget(self.live_dashboard)
        self.panels.addTab(self.live_scroll, "Live")
        self.panels.addTab(self.artifacts, "Artifacts")
        self.panels.addTab(self.rooms, "Room schedule")
        self.rooms.book_requested.connect(self._book_room)
        self.rooms.release_requested.connect(self._release_room)
        self.rooms.refresh_requested.connect(self._refresh_rooms)
        columns.addWidget(self.panels)
        columns.setSizes([1050, 400])

        footer = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("muted")
        self.event_label = QLabel("0 events")
        self.event_label.setObjectName("muted")
        self.approve_button = QPushButton("Approve spec")
        self.decline_button = QPushButton("Decline spec")
        self.approve_button.setEnabled(False)
        self.decline_button.setEnabled(False)
        self.approve_button.clicked.connect(lambda: self.approval_decision.emit(True))
        self.decline_button.clicked.connect(lambda: self.approval_decision.emit(False))
        self.export_button = QPushButton("Export deliverable ZIP")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self._export_deliverable)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.event_label)
        footer.addWidget(self.approve_button)
        footer.addWidget(self.decline_button)
        footer.addWidget(self.export_button)
        main_page_layout.addLayout(footer)

        self.llm_console = LLMConsoleTab()
        settings_page = self._build_settings_page()
        self.main_tabs.addTab(main_page, "Main")
        self.main_tabs.addTab(self.llm_console, "LLM Console")
        self.main_tabs.addTab(settings_page, "Settings")
        root.addWidget(self.main_tabs, 1)

    def _build_live_dashboard(self) -> QWidget:
        dashboard = QWidget()
        layout = QVBoxLayout(dashboard)
        layout.setContentsMargins(7, 9, 7, 7)
        layout.setSpacing(10)
        self.tech_stack = QListWidget()
        self.tech_stack.setObjectName("roomSummary")
        self.tech_stack.setMaximumHeight(110)
        self.tech_stack.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tech_panel, self.tech_count = self._live_panel(
            "ARCHITECTURE", "Tech stack", self.tech_stack, 125
        )
        self.plan_list = QListWidget()
        self.plan_list.setObjectName("roomSummary")
        self.plan_list.setMaximumHeight(205)
        self.plan_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plan_panel, self.plan_count = self._live_panel(
            "THE ROUTE", "Plan of action", self.plan_list, 215
        )
        self.updates_panel, self.updates_count = self._live_panel(
            "FROM MAYA", "Along the way", self.updates, 220
        )
        self.transcript_panel, self.transcript_count = self._live_panel(
            "AT THE TABLE",
            "What they're saying",
            self.transcript,
            245,
        )

        schedule_frame = QFrame()
        schedule_frame.setObjectName("livePanel")
        schedule_layout = QVBoxLayout(schedule_frame)
        schedule_layout.setContentsMargins(13, 10, 13, 10)
        schedule_layout.setSpacing(6)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        kicker = QLabel("ROOMS")
        kicker.setObjectName("panelKicker")
        title = QLabel("Who's meeting where")
        title.setObjectName("panelTitle")
        title_box.addWidget(kicker)
        title_box.addWidget(title)
        heading.addLayout(title_box)
        heading.addStretch(1)
        self.room_count = QLabel("0 active")
        self.room_count.setObjectName("countBadge")
        heading.addWidget(self.room_count)
        schedule_layout.addLayout(heading)
        self.room_summary = QListWidget()
        self.room_summary.setObjectName("roomSummary")
        self.room_summary.setMaximumHeight(120)
        self.room_summary.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.room_summary.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        schedule_layout.addWidget(self.room_summary, 1)
        manage_rooms = QPushButton("Manage room bookings")
        manage_rooms.setObjectName("textButton")
        manage_rooms.clicked.connect(lambda: self.panels.setCurrentWidget(self.rooms))
        schedule_layout.addWidget(manage_rooms, 0, Qt.AlignmentFlag.AlignRight)
        self.schedule_panel = schedule_frame

        layout.addWidget(self.tech_panel, 1)
        layout.addWidget(self.plan_panel, 2)
        layout.addWidget(self.updates_panel, 3)
        layout.addWidget(self.transcript_panel, 3)
        layout.addWidget(self.schedule_panel, 2)
        self._refresh_tech_stack()
        self._update_plan("0 of 8", "waiting")
        return dashboard

    def _build_settings_page(self) -> QWidget:
        self.settings_tabs = QTabWidget()
        self.settings_tabs.setObjectName("settingsTabs")

        agents_page = QWidget()
        agents_layout = QVBoxLayout(agents_page)
        agents_layout.setContentsMargins(18, 18, 18, 18)
        agents_layout.setSpacing(12)
        agents_title = QLabel("Your team")
        agents_title.setObjectName("panelTitle")
        agents_description = QLabel(
            "Names and agent prompts are saved to this desktop profile and used on future runs."
        )
        agents_description.setObjectName("muted")
        agents_description.setWordWrap(True)
        agents_layout.addWidget(agents_title)
        agents_layout.addWidget(agents_description)
        self.agent_editor = AgentSettingsEditor(
            self.agent_configuration,
            self.defaults,
        )
        self.agent_editor.configuration_saved.connect(self._agent_configuration_saved)
        agents_layout.addWidget(self.agent_editor, 1)
        self.settings_tabs.addTab(agents_page, "Agents")

        animation_page = QWidget()
        animation_layout = QVBoxLayout(animation_page)
        animation_layout.setContentsMargins(18, 18, 18, 18)
        animation_layout.setSpacing(12)
        animation_title = QLabel("Office animation")
        animation_title.setObjectName("panelTitle")
        animation_note = QLabel("Choose how quickly the team moves around the office.")
        animation_note.setObjectName("muted")
        animation_layout.addWidget(animation_title)
        animation_layout.addWidget(animation_note)
        animation_label = QLabel("Animation speed")
        animation_layout.addWidget(animation_label)
        self.speed = QComboBox()
        speed_options = ((0.5, "0.5×"), (1.0, "1×"), (2.0, "2×"), (4.0, "4×"))
        for value, label in speed_options:
            self.speed.addItem(label, value)
        stored_speed = self.settings.value(ANIMATION_SETTINGS_KEY)
        try:
            speed_value = float(stored_speed) if stored_speed is not None else 1.0
        except (TypeError, ValueError):
            speed_value = 1.0
        speed_index = self.speed.findData(speed_value)
        self.speed.setCurrentIndex(speed_index if speed_index >= 0 else 1)
        self.speed.currentIndexChanged.connect(self._speed_changed)
        animation_layout.addWidget(self.speed)
        animation_layout.addStretch(1)
        self.settings_tabs.addTab(animation_page, "Animation")

        model_page = QWidget()
        model_layout = QVBoxLayout(model_page)
        model_layout.setContentsMargins(18, 18, 18, 18)
        model_layout.setSpacing(12)
        model_title = QLabel("Model for new runs")
        model_title.setObjectName("panelTitle")
        model_note = QLabel(
            "Choose a Gemini model ID available to your API account, or type another model ID. "
            "This change applies to future runs."
        )
        model_note.setObjectName("muted")
        model_note.setWordWrap(True)
        model_layout.addWidget(model_title)
        model_layout.addWidget(model_note)
        model_layout.addWidget(QLabel("Gemini model"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        model_options = (
            self.model_name,
            os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        )
        for model in dict.fromkeys(model_options):
            self.model_combo.addItem(model)
        self.model_combo.setCurrentText(self.model_name)
        model_layout.addWidget(self.model_combo)
        save_model = QPushButton("Save model")
        save_model.clicked.connect(self._save_model)
        model_layout.addWidget(save_model, 0, Qt.AlignmentFlag.AlignLeft)
        self.model_saved_label = QLabel(f"Saved model: {self.model_name}")
        self.model_saved_label.setObjectName("muted")
        model_layout.addWidget(self.model_saved_label)
        model_layout.addStretch(1)
        self.settings_tabs.addTab(model_page, "LLM Model")

        return self.settings_tabs

    @staticmethod
    def _live_panel(
        kicker_text: str,
        title_text: str,
        content: QWidget,
        minimum_height: int,
    ) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setObjectName("livePanel")
        frame.setMinimumHeight(minimum_height)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(13, 10, 13, 9)
        layout.setSpacing(7)
        heading = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        kicker = QLabel(kicker_text)
        kicker.setObjectName("panelKicker")
        title = QLabel(title_text)
        title.setObjectName("panelTitle")
        title_box.addWidget(kicker)
        title_box.addWidget(title)
        heading.addLayout(title_box)
        heading.addStretch(1)
        count = QLabel("0")
        count.setObjectName("countBadge")
        heading.addWidget(count)
        layout.addLayout(heading)
        layout.addWidget(content, 1)
        return frame, count

    def _refresh_tech_stack(self, values: list[str] | None = None) -> None:
        if values is not None:
            self._tech_stack_items = values
        items = getattr(self, "_tech_stack_items", [])
        self.tech_stack.clear()
        if items:
            self.tech_stack.addItems(items[:8])
        else:
            self.tech_stack.addItem("Waiting for the Architect's design…")
        self.tech_count.setText(str(len(items)) if items else "pending")

    def _update_plan(self, stage_value: Any, status: Any) -> None:
        stage_parts = str(stage_value or "").split("of")
        try:
            current = int(stage_parts[0].strip()) if len(stage_parts) == 2 else 0
        except ValueError:
            current = 0
        normalized_status = str(status or "in progress").lower()
        steps = (
            "Write the project specification",
            "Design the architecture and threat model",
            "Review and approve the design",
            "Implement the approved design",
            "Run tests, security, and code review",
            "Resolve review findings",
            "Write usage documentation",
            "Complete final acceptance and delivery",
        )
        self.plan_list.clear()
        for index, step in enumerate(steps, start=1):
            if (normalized_status == "completed" and current >= 8) or index < current:
                marker = "✓"
            elif index == current:
                marker = "!" if normalized_status in ("failed", "blocked") else "●"
            else:
                marker = "○"
            self.plan_list.addItem(f"{marker}  {step}")
        self.plan_count.setText(
            f"{min(current, 8)} / 8" if current else "ready"
        )

    def _save_model(self) -> None:
        model_name = self.model_combo.currentText().strip()
        if not model_name:
            QMessageBox.warning(self, "Model ID needed", "Enter a Gemini model ID.")
            return
        self.model_name = model_name
        self.settings.setValue(MODEL_SETTINGS_KEY, model_name)
        self.model_saved_label.setText(f"Saved model: {model_name}")
        self.statusBar().showMessage("Model selection saved for future runs.", 5000)

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f2efe8; color: #33352f; font-family: "Segoe UI"; }
            QLabel, QCheckBox { background: transparent; }
            QFrame#card { background: #faf8f3; border: 1px solid #e2ddd2; border-radius: 12px; }
            QFrame#officeCard { background: #eee8dc; border: 1px solid #dfd9cd; border-radius: 14px; }
            QFrame#livePanel { background: #faf8f3; border: 1px solid #e2ddd2; border-radius: 13px; }
            QLabel#brandMark { min-width: 38px; max-width: 38px; min-height: 38px; max-height: 38px;
                color: #55745c; background: #eef0e7; border: 1px solid #d5d9cd; border-radius: 12px;
                font: 600 21px Georgia; }
            QLabel#brandTitle { color: #3b3b34; font: 600 20px Georgia; }
            QLabel#provider { color: #63725e; background: #edf0e7; border: 1px solid #d7dfd1; border-radius: 11px; padding: 6px 9px; font-size: 9px; font-weight: 700; }
            QLabel#runId { color: #929087; font-size: 10px; }
            QLabel#muted { color: #85857c; }
            QLabel#sectionKicker, QLabel#panelKicker { color: #9b8064; font-size: 8px; font-weight: 700; letter-spacing: 1.1px; }
            QLabel#projectTitle { color: #3b3b34; font: 500 21px Georgia; }
            QLabel#floorDate, QLabel#panelTitle { color: #47483f; font: 500 14px Georgia; }
            QLabel#floorStatus { color: #76766d; font-size: 10px; padding-right: 10px; }
            QLabel#progressLabel { color: #5f765f; font-size: 10px; font-weight: 600; }
            QLabel#footnote { color: #9a968b; font-size: 9px; }
            QLabel#agentAvatar { color: white; border: 3px solid #faf8f3; border-radius: 21px; font: 600 17px Georgia; }
            QLabel#agentName { color: #414239; font: 600 14px Georgia; }
            QLabel#agentActivity { color: #77776e; font-size: 10px; }
            QLabel#artifactBadge, QLabel#countBadge { color: #71826a; background: #f5f4ed; border: 1px solid #e0ddd2; border-radius: 11px; padding: 4px 8px; font-size: 9px; }
            QPushButton { background: #fffdf8; border: 1px solid #ded9ce; border-radius: 7px; padding: 7px 11px; font-size: 10px; }
            QPushButton:hover { background: #f0f3eb; border-color: #9bab91; }
            QPushButton:disabled { color: #aaa59a; background: #f1eee8; }
            QPushButton#primaryButton { color: #fffdf8; background: #71866b; border-color: #73876c; font-weight: 600; }
            QPushButton#primaryButton:hover { background: #5f7559; }
            QPushButton#secondaryButton { color: #49644e; background: #edf1e8; border-color: #d7dfd1; }
            QPushButton#textButton { padding: 3px 4px; border: 0; color: #71866b; background: transparent; }
            QPushButton#textButton:hover { color: #49644e; background: transparent; text-decoration: underline; }
            QPlainTextEdit, QTextBrowser, QTreeWidget, QListWidget, QLineEdit, QComboBox, QSpinBox {
                background: #fffdf8; border: 1px solid #e1ddd2; border-radius: 7px; padding: 5px;
                selection-background-color: #dce5d6;
            }
            QListWidget#feedList, QListWidget#roomSummary { border: 0; background: transparent; padding: 0; outline: 0; }
            QListWidget#feedList::item { margin: 3px 1px; padding: 7px 8px; border-left: 2px solid #d2d7c8; color: #63645b; }
            QListWidget#feedList::item:selected { background: #f0f2eb; color: #45463e; }
            QListWidget#agentSettingsList { border: 0; background: #f5f2eb; padding: 8px; }
            QListWidget#agentSettingsList::item { margin: 2px 0; padding: 9px 10px; border-radius: 7px; color: #55564d; }
            QListWidget#agentSettingsList::item:selected { background: #edf0e7; color: #49644e; }
            QListWidget#roomSummary::item { padding: 4px 2px; color: #63645b; }
            QTabWidget::pane { background: #faf8f3; border: 1px solid #e2ddd2; border-radius: 8px; }
            QTabBar::tab { background: #ebe7de; border: 1px solid #e2ddd2; padding: 7px 10px; color: #77776e; font-size: 9px; }
            QTabBar::tab:selected { background: #faf8f3; color: #49644e; }
            QProgressBar { background: #e9e5db; border: 0; border-radius: 4px; height: 7px; text-align: center; }
            QProgressBar::chunk { background: #83977a; border-radius: 5px; }
            QHeaderView::section { background: #f1eee8; border: 0; padding: 5px; }
            """
        )

    def _load_agent_configuration(self) -> AgentConfiguration:
        stored = self.settings.value(SETTINGS_KEY)
        if not stored:
            return self.defaults
        try:
            data = json.loads(str(stored))
            return AgentConfiguration.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError) as error:
            self.statusBar().showMessage(f"Saved agent settings were invalid: {error}", 10_000)
            return self.defaults

    def _agent_configuration_saved(self, configuration: AgentConfiguration) -> None:
        self.agent_configuration = configuration
        self.settings.setValue(
            SETTINGS_KEY,
            json.dumps(self.agent_configuration.model_dump(mode="json"), ensure_ascii=False),
        )
        self.office.set_configuration(self.agent_configuration)
        self._select_agent(self.office.selected_role)
        self._refresh_rooms()
        self.statusBar().showMessage("Agent names and prompts saved for this desktop user.", 5000)

    def _start_run(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "A prompt is needed", "Describe the tool you want the team to build.")
            return
        if len(prompt) > 20_000:
            QMessageBox.warning(self, "Prompt is too long", "Keep the build prompt below 20,000 characters.")
            return
        if self._thread is not None:
            return
        self._stop_demo()
        run_id = f"run-{uuid4().hex}"
        project_directory = self._project_directory_for(prompt, run_id)
        try:
            project_directory.mkdir(parents=True, exist_ok=False)
        except OSError as error:
            QMessageBox.critical(
                self,
                "Could not create project folder",
                f"DevOffice could not create {project_directory}:\n{error}",
            )
            return
        self.current_run_id = run_id
        self.current_project_directory = project_directory
        self._reset_run_view()
        self._set_project_title(prompt)
        self.build_canvas.begin_run(prompt)
        self._refresh_tech_stack([])
        self._update_plan("1 of 8", "in_progress")
        self.llm_console.clear_calls()
        self.main_tabs.setCurrentIndex(0)
        self.last_result = None
        self.deliverable_path = None
        self.export_button.setEnabled(False)
        self.approve_button.setEnabled(False)
        self.decline_button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress_label.setText("Getting started")
        self.status_label.setText(f"Starting · {self.current_run_id}")
        self.run_id_label.setText(self.current_run_id)
        self.provider_label.setText("STARTING RUN")
        self.event_label.setText("0 events")
        self._refresh_history()

        self._thread = QThread(self)
        self._worker = GraphWorker(
            self.current_run_id,
            prompt,
            self.approval_checkbox.isChecked(),
            self.agent_configuration,
            CHECKPOINT_PATH,
            self.event_store,
            model_name=self.model_name,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.event_received.connect(self._handle_event)
        self._worker.llm_call_received.connect(self._handle_llm_call)
        self._worker.model_ready.connect(self._model_ready)
        self._worker.approval_requested.connect(self._approval_requested)
        self._worker.run_completed.connect(self._run_completed)
        self._worker.run_failed.connect(self._run_failed)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread_finished)
        self.approval_decision.connect(self._worker.resume_approval)
        self._thread.start()

    def _reset_run_view(self) -> None:
        self.events.clear()
        self._event_count = 0
        self._agent_activities.clear()
        self._tech_stack_items = []
        self.updates.clear()
        self.transcript.clear()
        self.updates_count.setText("0")
        self.transcript_count.setText("0")
        self.updates.addItem("Maya will leave a note when the team reaches a milestone.")
        self.transcript.addItem("Pull up a chair. The first meeting will show up here.")
        self.artifacts.set_result({})
        self.office.reset()
        self.build_canvas.begin_run("Loading a saved or sample run")
        self._refresh_tech_stack([])
        self._update_plan("0 of 8", "waiting")
        self.llm_console.clear_calls()
        self.floor_status.setText("Everyone at their desks")
        self.latest_artifact_label.clear()
        self.latest_artifact_label.setVisible(False)
        self._select_agent(AgentRole.ORCHESTRATOR.value)
        self._refresh_live_schedule()

    def _start_demo(self) -> None:
        if self._thread is not None:
            return
        self._stop_demo()
        self.current_run_id = DEMO_RUN_ID
        self.current_project_directory = None
        self._reset_run_view()
        self._set_project_title(
            "Build a CLI tool that converts CSV files to JSON with schema validation."
        )
        self.build_canvas.begin_run(
            "Build a CLI tool that converts CSV files to JSON with schema validation."
        )
        self._refresh_tech_stack([])
        self._update_plan("1 of 8", "in_progress")
        self.main_tabs.setCurrentIndex(0)
        self.last_result = None
        self.deliverable_path = None
        self.export_button.setEnabled(False)
        self.approve_button.setEnabled(False)
        self.decline_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress_label.setText("Getting started")
        self.provider_label.setText("DEMO RUN")
        self.run_id_label.setText(DEMO_RUN_ID)
        self.status_label.setText("The team is getting settled.")
        self.event_label.setText(f"0 / {len(DEMO_EVENTS)} events")
        self._demo_cursor = 0
        self._demo_running = True
        self.run_button.setEnabled(False)
        self.sample_run_button.setEnabled(False)
        self.demo_button.setEnabled(False)
        self.pause_button.setText("Pause")
        self.pause_button.setEnabled(True)
        self.pause_button.setVisible(True)
        self.demo_timer.start(100)

    def _set_project_title(self, prompt: str) -> None:
        title = prompt.strip().splitlines()[0].strip().rstrip(".")
        for prefix in ("Build a ", "Build an ", "Create a ", "Create an "):
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix):]
                break
        if len(title) > 46:
            title = title[:43].rstrip() + "…"
        self.project_title_label.setText(title or "A new team project")
        if self.current_project_directory is not None:
            self.project_subtitle_label.setText(
                f"Project folder · {self.current_project_directory}"
            )
        else:
            self.project_subtitle_label.setText("From your prompt · acceptance criteria tracked.")

    @staticmethod
    def _project_slug(prompt: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", prompt.casefold()).strip("-")
        return (normalized[:48].rstrip("-") or "new-project")

    @classmethod
    def _project_directory_for(cls, prompt: str, run_id: str) -> Path:
        return PROJECTS_DIR / f"{cls._project_slug(prompt)}-{run_id}"

    def _play_next_demo_event(self) -> None:
        if not self._demo_running:
            return
        if self._demo_cursor >= len(DEMO_EVENTS):
            self._stop_demo()
            self.status_label.setText("Sample run complete · ready for your build.")
            self.progress.setValue(100)
            self.progress_label.setText("8 of 8 · completed")
            return
        event_type, agent, room, payload = DEMO_EVENTS[self._demo_cursor]
        event = EventEnvelope(
            run_id=DEMO_RUN_ID,
            type=EventType(event_type),
            agent=agent,
            room=room,
            payload=payload,
        )
        self._handle_event(event.model_dump(mode="json"))
        self._demo_cursor += 1
        self.event_label.setText(f"{self._demo_cursor} / {len(DEMO_EVENTS)} events")
        if self._demo_cursor < len(DEMO_EVENTS):
            interval = max(120, round(1150 / float(self.speed.currentData())))
            self.demo_timer.start(interval)

    def _toggle_demo(self) -> None:
        if not self._demo_running:
            return
        if self.demo_timer.isActive():
            self.demo_timer.stop()
            self.pause_button.setText("Continue")
            self.status_label.setText("Sample run paused.")
        else:
            self.pause_button.setText("Pause")
            self.status_label.setText("The team is working through the sample.")
            self.demo_timer.start(max(100, round(1150 / float(self.speed.currentData()))))

    def _stop_demo(self) -> None:
        if hasattr(self, "demo_timer"):
            self.demo_timer.stop()
        self._demo_running = False
        if hasattr(self, "pause_button"):
            self.pause_button.setEnabled(False)
            self.pause_button.setText("Pause")
            self.pause_button.setVisible(False)
        if hasattr(self, "demo_button"):
            self.demo_button.setEnabled(True)
        if hasattr(self, "sample_run_button"):
            self.sample_run_button.setEnabled(True)
        if hasattr(self, "run_button") and self._thread is None:
            self.run_button.setEnabled(True)

    def _handle_event(self, event_data: dict[str, Any]) -> None:
        event = EventEnvelope.model_validate(event_data)
        self.events.append(event.model_dump(mode="json"))
        self._event_count += 1
        self.event_label.setText(f"{self._event_count} events")
        self.office.apply_event(event_data)
        role = event.payload.get("agent_role")
        if role not in self.agent_configuration.agents:
            role = next(
                (
                    candidate.value
                    for candidate, profile in self.agent_configuration.agents.items()
                    if profile.name == event.agent
                ),
                None,
            )
        if event.type == EventType.AGENT_STATUS and role:
            self._agent_activities[role] = str(event.payload.get("activity", "working"))
            if role == self.office.selected_role:
                self._select_agent(role)
        elif event.type == EventType.MILESTONE_UPDATE:
            self._append_update(event)
            self._set_progress(event.payload.get("stage"), event.payload.get("status"))
            self._update_plan(event.payload.get("stage"), event.payload.get("status"))
            self.build_canvas.set_progress(
                self.progress.value(),
                str(event.payload.get("status", "in progress")),
            )
            self.status_label.setText(str(event.payload.get("message", "The team reached a milestone.")))
        elif event.type in (EventType.MEETING_STARTED, EventType.MEETING_MESSAGE, EventType.MEETING_ENDED):
            self._append_transcript(event)
        elif event.type in (EventType.ROOM_BOOKED, EventType.ROOM_RELEASED):
            self._append_transcript(event)
            self._refresh_rooms()
            self._refresh_live_schedule()
        elif event.type in (EventType.REVIEW_VERDICT, EventType.SECURITY_FINDING, EventType.TEST_RESULT):
            self._append_transcript(event)
        elif event.type == EventType.ARTIFACT_CREATED:
            self.latest_artifact_label.setText(
                f"Latest: {event.payload.get('artifact', 'artifact')}"
            )
            self.latest_artifact_label.setVisible(True)
            self.build_canvas.apply_artifact(event.payload)
            if event.payload.get("artifact") == "design":
                dependencies = BuildCanvasWidget._strings(event.payload.get("dependencies"))
                components = BuildCanvasWidget._strings(event.payload.get("components"))
                self._refresh_tech_stack(dependencies or components)
        elif event.type == EventType.ERROR:
            self.status_label.setText(str(event.payload.get("message", "The run failed.")))
        if event.type == EventType.MEETING_STARTED:
            self.floor_status.setText(f"In a meeting · {event.room or 'meeting room'}")
        elif event.type == EventType.MEETING_ENDED:
            self.floor_status.setText("Everyone at their desks")
        if event.type == EventType.RUN_COMPLETE:
            self.status_label.setText(
                f"Run {event.payload.get('status', 'complete')}: "
                f"{event.payload.get('summary', '')}"
            )
        if event.run_id != DEMO_RUN_ID:
            self._refresh_history()

    def _append_update(self, event: EventEnvelope) -> None:
        timestamp = event.ts.astimezone().strftime("%I:%M %p")
        stage = str(event.payload.get("stage", "Update"))
        message = str(event.payload.get("message", ""))
        item = QListWidgetItem(f"{stage}  ·  {timestamp}\n{message}")
        risks = event.payload.get("risks", [])
        if risks:
            item.setText(f"{item.text()}\nWorth keeping an eye on")
        if self.updates.count() == 1 and self.updates.item(0).text().startswith("Maya will leave"):
            self.updates.clear()
        self.updates.insertItem(0, item)
        while self.updates.count() > 5:
            self.updates.takeItem(self.updates.count() - 1)
        self.updates_count.setText(str(self.updates.count()))

    def _append_transcript(self, event: EventEnvelope) -> None:
        timestamp = event.ts.astimezone().strftime("%I:%M")
        role = event.payload.get("agent_role")
        speaker = event.agent or "Team"
        if role and role in self.agent_configuration.agents:
            speaker = self.agent_configuration.agents[role].name
        if event.type == EventType.MEETING_MESSAGE:
            body = str(event.payload.get("text", ""))
            line = f"{speaker}  ·  {timestamp}\n{body}"
        elif event.type == EventType.MEETING_STARTED:
            line = f"↗  {event.payload.get('topic', 'Team meeting')} started  ·  {timestamp}"
        elif event.type == EventType.MEETING_ENDED:
            line = f"✓  Meeting wrapped up  ·  {timestamp}"
        elif event.type == EventType.ROOM_BOOKED:
            line = f"{speaker} booked {event.room}: {event.payload.get('topic', 'Meeting')}"
        elif event.type == EventType.ROOM_RELEASED:
            line = f"{speaker} released {event.room}"
        elif event.type == EventType.REVIEW_VERDICT:
            line = f"{speaker} · {event.payload.get('phase', 'review')} review: {event.payload.get('verdict', '')}"
        elif event.type == EventType.TEST_RESULT:
            line = f"{speaker} · tests: {event.payload.get('passed', 0)} passed, {event.payload.get('failed', 0)} failed"
        else:
            finding = event.payload.get("finding")
            if finding:
                line = f"{speaker} · {finding.get('severity', 'finding')}: {finding.get('title', '')}"
            else:
                line = f"{speaker} · {event.payload.get('phase', 'security')} gate: {event.payload.get('gate', '')}"
        if self.transcript.count() == 1 and self.transcript.item(0).text().startswith("Pull up a chair"):
            self.transcript.clear()
        self.transcript.addItem(line)
        while self.transcript.count() > 8:
            self.transcript.takeItem(0)
        self.transcript.scrollToBottom()
        self.transcript_count.setText(str(self.transcript.count()))

    def _set_progress(self, stage_value: Any, status: Any) -> None:
        stage = str(stage_value or "")
        parts = stage.split("of")
        if len(parts) == 2:
            try:
                current, total = int(parts[0].strip()), int(parts[1].strip())
                self.progress.setValue(max(0, min(100, round(current * 100 / total))))
            except ValueError:
                pass
        readable_status = str(status or "in progress").replace("_", " ")
        self.progress_label.setText(
            f"{stage} · {readable_status}" if stage else readable_status.title()
        )

    def _handle_llm_call(self, record: dict[str, Any]) -> None:
        self.llm_console.add_call(record)

    def _model_ready(self, provider: str, model: str) -> None:
        self.provider_label.setText(f"{provider.title()} · {model}")

    def _approval_requested(self, state: dict[str, Any]) -> None:
        spec = state.get("spec", {})
        self.artifacts.set_result(state)
        self.progress_label.setText("Specification ready · waiting for your decision")
        self.status_label.setText("Review the specification, then approve or decline.")
        self.approve_button.setEnabled(True)
        self.decline_button.setEnabled(True)
        self.panels.setCurrentWidget(self.artifacts)
        self.artifacts.preview.setPlainText(json.dumps(spec, ensure_ascii=False, indent=2))

    def _run_completed(self, result: dict[str, Any]) -> None:
        self.last_result = result
        self.artifacts.set_result(result)
        self.approve_button.setEnabled(False)
        self.decline_button.setEnabled(False)
        acceptance = result.get("final_acceptance", {})
        status = acceptance.get("status", "completed")
        self.status_label.setText(f"Run {status}: {acceptance.get('summary', '')}")
        if status == "completed":
            self.progress.setValue(100)
            self.progress_label.setText("8 of 8 · completed")
        self._update_plan("8 of 8", str(status))
        self.build_canvas.set_progress(self.progress.value(), str(status))
        try:
            self.deliverable_path = save_run_artifacts(
                self.runs_dir / str(self.current_run_id),
                result,
                project_directory=self.current_project_directory,
            )
            self.export_button.setEnabled(self.deliverable_path.exists())
            if self.current_project_directory is not None:
                self.statusBar().showMessage(
                    f"Project saved to {self.current_project_directory}",
                    12_000,
                )
        except (OSError, ValueError) as error:
            self.statusBar().showMessage(f"Could not package deliverable: {error}", 10_000)
        self._refresh_history()

    def _run_failed(self, message: str) -> None:
        if message.startswith("GeminiRateLimitError:"):
            self.status_label.setText(
                "Run failed · Gemini rate limit/quota. Check AI Studio usage or wait, then retry."
            )
            self.statusBar().showMessage(message, 15_000)
        else:
            self.status_label.setText(f"Run failed · {message}")
        self.progress_label.setText("Run stopped")

    def _thread_finished(self) -> None:
        self.run_button.setEnabled(True)
        self.approve_button.setEnabled(False)
        self.decline_button.setEnabled(False)
        self._worker = None
        if self._thread is not None:
            self._thread.deleteLater()
            self._thread = None
        self._refresh_history()

    def _select_agent(self, role: str) -> None:
        self.office.set_selected_agent(role)
        if role not in self.agent_configuration.agents:
            return
        profile = self.agent_configuration.agents[AgentRole(role)]
        activity = self._agent_activities.get(role, "Waiting for the next task")
        color = AGENT_COLORS.get(role, "#71866b")
        self.agent_avatar.setText(profile.name[:1].upper())
        self.agent_avatar.setStyleSheet(
            f"background: {color}; color: white; border-radius: 21px; "
            "border: 3px solid #faf8f3;"
        )
        self.agent_name.setText(f"{profile.name}  ·  {role.replace('_', ' ').title()}")
        self.agent_activity.setText(activity)

    def _speed_changed(self) -> None:
        speed = float(self.speed.currentData())
        self.settings.setValue(ANIMATION_SETTINGS_KEY, str(speed))
        self.office.set_speed(speed)
        if self._demo_running and self.demo_timer.isActive():
            self.demo_timer.start(max(100, round(1150 / speed)))

    def _book_room(self) -> None:
        dialog = BookingDialog(
            {role: self.agent_configuration.agents[role].name for role in AgentRole},
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        room_id, organizer, attendees, topic, duration = dialog.booking_request()
        try:
            booking = self.room_service.book_room(
                room_id,
                organizer,
                attendees,
                topic,
                duration,
            )
        except (BookingConflictError, ValueError) as error:
            QMessageBox.warning(self, "Could not book room", str(error))
            return
        role = self._role_for_name(booking.organizer)
        event = EventEnvelope(
            run_id="office",
            type=EventType.ROOM_BOOKED,
            agent=booking.organizer,
            room=ROOM_BY_ID[booking.room_id].name,
            payload={
                **booking.model_dump(mode="json"),
                **({"agent_role": role} if role else {}),
            },
        )
        self.event_store.append(event)
        self._handle_event(event.model_dump(mode="json"))

    def _release_room(self, booking_id: str, organizer: str) -> None:
        try:
            booking = self.room_service.release_room(booking_id, organizer)
        except ValueError as error:
            QMessageBox.warning(self, "Could not release room", str(error))
            return
        role = self._role_for_name(booking.organizer)
        event = EventEnvelope(
            run_id="office",
            type=EventType.ROOM_RELEASED,
            agent=booking.organizer,
            room=ROOM_BY_ID[booking.room_id].name,
            payload={
                **booking.model_dump(mode="json"),
                **({"agent_role": role} if role else {}),
            },
        )
        self.event_store.append(event)
        self._handle_event(event.model_dump(mode="json"))

    def _role_for_name(self, name: str) -> str | None:
        return next(
            (role.value for role, profile in self.agent_configuration.agents.items() if profile.name == name),
            None,
        )

    def _refresh_rooms(self) -> None:
        self.rooms.set_schedules(self.room_service.list_rooms())
        self._refresh_live_schedule()

    def _refresh_live_schedule(self) -> None:
        if not hasattr(self, "room_summary"):
            return
        latest_by_room: dict[str, EventEnvelope] = {}
        for event_data in reversed(self.events):
            if event_data.get("type") not in ("room_booked", "room_released"):
                continue
            room = event_data.get("room")
            if room and room not in latest_by_room:
                latest_by_room[str(room)] = EventEnvelope.model_validate(event_data)
        now = datetime.now(timezone.utc)
        active_count = 0
        self.room_summary.clear()
        schedules = {row.room.id: row for row in self.room_service.list_rooms()}
        for room in ROOM_BY_ID.values():
            event = latest_by_room.get(room.name)
            if event is not None and event.type == EventType.ROOM_BOOKED:
                topic = str(event.payload.get("topic", "Meeting"))
                organizer = event.agent or str(event.payload.get("organizer", "Team"))
                line = f"●  {room.name}  ·  {topic} with {organizer}"
                active_count += 1
            else:
                schedule = schedules.get(room.id)
                active_booking = next(
                    (
                        booking for booking in schedule.schedule
                        if booking.status == "booked" and booking.starts_at <= now < booking.ends_at
                    ),
                    None,
                ) if schedule else None
                if active_booking:
                    line = f"●  {room.name}  ·  {active_booking.topic} with {active_booking.organizer}"
                    active_count += 1
                else:
                    line = f"○  {room.name}  ·  Free for a chat"
            self.room_summary.addItem(line)
        self.room_count.setText(f"{active_count} active")

    def _refresh_history(self) -> None:
        current = self.current_run_id
        self.history.blockSignals(True)
        self.history.clear()
        self.history.addItem("Recent runs", None)
        run_directories = [
            path
            for path in self.runs_dir.iterdir()
            if path.is_dir() and (path / "events.jsonl").is_file()
        ] if self.runs_dir.exists() else []
        for path in sorted(run_directories, key=lambda item: item.stat().st_mtime, reverse=True)[:30]:
            self.history.addItem(path.name, path.name)
        if current:
            index = self.history.findData(current)
            if index >= 0:
                self.history.setCurrentIndex(index)
        self.history.blockSignals(False)

    def _history_selected(self, index: int) -> None:
        run_id = self.history.itemData(index)
        if not run_id or run_id == self.current_run_id or self._thread is not None:
            return
        self._stop_demo()
        self.current_run_id = str(run_id)
        self.current_project_directory = self._find_project_directory(self.current_run_id)
        self._reset_run_view()
        self.main_tabs.setCurrentIndex(0)
        if self.current_project_directory is not None:
            self.project_subtitle_label.setText(
                f"Project folder · {self.current_project_directory}"
            )
        else:
            self.project_subtitle_label.setText("Saved run · see artifacts for the generated files.")
        self.run_id_label.setText(self.current_run_id)
        self.provider_label.setText("SAVED RUN")
        for event in self.event_store.replay(self.current_run_id):
            self._handle_event(event.model_dump(mode="json"))
        try:
            self.llm_console.set_records(self._read_llm_calls(self.current_run_id))
        except (OSError, json.JSONDecodeError, ValueError) as error:
            self.statusBar().showMessage(f"Could not replay LLM console: {error}", 10_000)
        state_path = self.runs_dir / self.current_run_id / "artifacts" / "final_state.json"
        if state_path.is_file():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.last_result = state
            self.artifacts.set_result(state)
            spec = state.get("spec", {})
            goals = spec.get("goals", []) if isinstance(spec, dict) else []
            if goals:
                self._set_project_title(str(goals[0]))
            zip_path = self.runs_dir / self.current_run_id / "artifacts" / "deliverable.zip"
            self.deliverable_path = zip_path if zip_path.is_file() else None
            self.export_button.setEnabled(self.deliverable_path is not None)
        self.status_label.setText(f"Replaying saved run · {self.current_run_id}")

    def _find_project_directory(self, run_id: str) -> Path | None:
        if not PROJECTS_DIR.is_dir():
            return None
        suffix = f"-{run_id}"
        return next(
            (
                path
                for path in PROJECTS_DIR.iterdir()
                if path.is_dir() and path.name.endswith(suffix)
            ),
            None,
        )

    def _read_llm_calls(self, run_id: str) -> list[dict[str, Any]]:
        call_log = self.runs_dir / run_id / "llm_calls.jsonl"
        if not call_log.is_file():
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(call_log.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"LLM call record at line {line_number} is not an object")
            records.append(record)
        return records

    def _export_deliverable(self) -> None:
        if self.deliverable_path is None or not self.deliverable_path.is_file():
            return
        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export DevOffice deliverable",
            f"devoffice-{self.current_run_id}.zip",
            "ZIP archive (*.zip)",
        )
        if not destination:
            return
        try:
            copy2(self.deliverable_path, destination)
        except OSError as error:
            QMessageBox.critical(self, "Export failed", str(error))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(destination).parent)))
        self.statusBar().showMessage(f"Deliverable exported to {destination}", 8000)


def main() -> int:
    app = QApplication([])
    register_windows_fonts()
    app.setApplicationName("DevOffice")
    app.setOrganizationName("DevOffice")
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()
