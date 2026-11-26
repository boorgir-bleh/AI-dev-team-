from typing import Any

from pydantic import ValidationError
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from backend.agents.config import AgentConfiguration, AgentRole
from backend.tools.rooms import ROOMS


class AgentSettingsEditor(QWidget):
    configuration_saved = pyqtSignal(object)

    def __init__(
        self,
        configuration: AgentConfiguration,
        defaults: AgentConfiguration,
        parent: QWidget | None = None,
        *,
        show_save_button: bool = True,
    ) -> None:
        super().__init__(parent)
        self._configuration = configuration
        self._defaults = defaults
        self._fields: dict[str, tuple[QLineEdit, QTextEdit, QTextEdit]] = {}

        layout = QVBoxLayout(self)
        intro = QVBoxLayout()
        heading = QLabel("Make the team your own")
        heading.setStyleSheet("font: 500 21px Georgia; color: #414239;")
        intro.addWidget(heading)
        intro.addWidget(QLabel(
            "Customize names and prompts. Use {{agent_name}} and {{context}} as placeholders."
        ))
        layout.addLayout(intro)
        editor = QHBoxLayout()
        self.agent_list = QListWidget()
        self.agent_list.setFixedWidth(190)
        self.agent_list.setObjectName("agentSettingsList")
        self.pages = QStackedWidget()
        for role in AgentRole:
            profile = configuration.agents[role]
            tab = QWidget()
            form = QFormLayout(tab)
            name = QLineEdit(profile.name)
            name.setMaxLength(80)
            system_prompt = QTextEdit()
            system_prompt.setPlainText(profile.system_prompt)
            task_prompt = QTextEdit()
            task_prompt.setPlainText(profile.task_prompt)
            system_prompt.setMinimumHeight(190)
            task_prompt.setMinimumHeight(150)
            form.addRow("Display name", name)
            form.addRow("System prompt", system_prompt)
            form.addRow("Task prompt", task_prompt)
            self._fields[role.value] = (name, system_prompt, task_prompt)
            self.agent_list.addItem(role.value.replace("_", " ").title())
            self.pages.addWidget(tab)
        self.agent_list.setCurrentRow(0)
        self.agent_list.currentRowChanged.connect(self.pages.setCurrentIndex)
        editor.addWidget(self.agent_list)
        editor.addWidget(self.pages, 1)
        layout.addLayout(editor, 1)

        actions = QHBoxLayout()
        self.reset_button = QPushButton("Restore defaults")
        self.reset_button.clicked.connect(self._restore_defaults)
        actions.addWidget(self.reset_button)
        actions.addStretch(1)
        self.save_button: QPushButton | None = None
        if show_save_button:
            self.save_button = QPushButton("Save agent settings")
            self.save_button.clicked.connect(self._save_configuration)
            actions.addWidget(self.save_button)
        layout.addLayout(actions)

    @property
    def agent_configuration(self) -> AgentConfiguration:
        return self._configuration

    def _restore_defaults(self) -> None:
        for role, profile in self._defaults.agents.items():
            name, system_prompt, task_prompt = self._fields[role.value]
            name.setText(profile.name)
            system_prompt.setPlainText(profile.system_prompt)
            task_prompt.setPlainText(profile.task_prompt)

    def _collect_configuration(self) -> AgentConfiguration | None:
        value: dict[str, Any] = {"agents": {}}
        for role in AgentRole:
            name, system_prompt, task_prompt = self._fields[role.value]
            value["agents"][role.value] = {
                "name": name.text(),
                "system_prompt": system_prompt.toPlainText(),
                "task_prompt": task_prompt.toPlainText(),
            }
        try:
            return AgentConfiguration.model_validate(value)
        except ValidationError as error:
            QMessageBox.warning(self, "Invalid agent settings", str(error))
            return None

    def _save_configuration(self) -> None:
        configuration = self._collect_configuration()
        if configuration is None:
            return
        self._configuration = configuration
        self.configuration_saved.emit(configuration)


class AgentSettingsDialog(QDialog):
    def __init__(
        self,
        configuration: AgentConfiguration,
        defaults: AgentConfiguration,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("DevOffice · Agent settings")
        self.resize(860, 680)
        self._configuration = configuration
        self.editor = AgentSettingsEditor(
            configuration,
            defaults,
            self,
            show_save_button=False,
        )
        self._fields = self.editor._fields
        self.agent_list = self.editor.agent_list
        self.pages = self.editor.pages

        layout = QVBoxLayout(self)
        layout.addWidget(self.editor, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def agent_configuration(self) -> AgentConfiguration:
        return self._configuration

    def _restore_defaults(self) -> None:
        self.editor._restore_defaults()

    def _save_and_accept(self) -> None:
        configuration = self.editor._collect_configuration()
        if configuration is None:
            return
        self._configuration = configuration
        self.accept()


class BookingDialog(QDialog):
    def __init__(
        self,
        names: dict[AgentRole, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Book a meeting room")
        self.resize(460, 520)
        self.room = QComboBox()
        for room in ROOMS:
            self.room.addItem(room.name, room.id)
        self.organizer = QComboBox()
        for role in AgentRole:
            self.organizer.addItem(names[role], role.value)
        self.attendees = QListWidget()
        for role in AgentRole:
            item = QListWidgetItem(names[role])
            item.setData(Qt.ItemDataRole.UserRole, role.value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.attendees.addItem(item)
        self.topic = QLineEdit("Team check-in")
        self.duration = QSpinBox()
        self.duration.setRange(1, 480)
        self.duration.setValue(30)

        form = QFormLayout()
        form.addRow("Room", self.room)
        form.addRow("Organizer", self.organizer)
        form.addRow("Attendees", self.attendees)
        form.addRow("Topic", self.topic)
        form.addRow("Duration (minutes)", self.duration)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Book room")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def booking_request(self) -> tuple[str, str, list[str], str, int]:
        attendees = [
            self.attendees.item(index).text()
            for index in range(self.attendees.count())
            if self.attendees.item(index).checkState() == Qt.CheckState.Checked
        ]
        if not attendees:
            attendees = [self.organizer.currentText()]
        return (
            str(self.room.currentData()),
            self.organizer.currentText(),
            attendees,
            self.topic.text().strip(),
            self.duration.value(),
        )
