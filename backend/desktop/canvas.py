from typing import Any

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class BuildCanvasWidget(QWidget):
    """Paints a safe, non-executing wireframe preview from the live design artifacts."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(420, 300)
        self.prompt_title = "Your project"
        self.components: list[str] = []
        self.dependencies: list[str] = []
        self.files: list[str] = []
        self.status = "Waiting for a new build"
        self.progress = 0

    def begin_run(self, prompt: str) -> None:
        first_line = prompt.strip().splitlines()[0] if prompt.strip() else ""
        self.prompt_title = first_line[:56] or "Your project"
        self.components = []
        self.dependencies = []
        self.files = []
        self.status = "Maya is preparing the specification"
        self.progress = 0
        self.update()

    def apply_artifact(self, payload: dict[str, Any]) -> None:
        artifact = payload.get("artifact")
        if artifact == "spec":
            goals = payload.get("goals", [])
            if goals:
                self.prompt_title = str(goals[0])[:56]
            self.status = "Specification ready"
        elif artifact == "design":
            self.components = self._strings(payload.get("components"))
            self.dependencies = self._strings(payload.get("dependencies"))
            self.files = self._strings(payload.get("file_tree"))
            self.status = "Architecture mapped"
        elif artifact in ("code", "documentation"):
            self.files = self._strings(payload.get("files")) or self.files
            self.status = "Implementation in progress" if artifact == "code" else "Documentation in progress"
        self.update()

    def set_progress(self, progress: int, status: str) -> None:
        self.progress = max(0, min(100, progress))
        self.status = status.replace("_", " ").title()
        self.update()

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if isinstance(item, (str, int, float))]

    def paintEvent(self, event: Any) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#eee8dc"))

        scale = min((self.width() - 24) / 860, (self.height() - 24) / 460)
        scale = max(0.35, scale)
        painter.translate((self.width() - 860 * scale) / 2, (self.height() - 460 * scale) / 2)
        painter.scale(scale, scale)

        painter.setPen(QPen(QColor("#ded8cc"), 1))
        painter.setBrush(QColor("#faf8f3"))
        painter.drawRoundedRect(QRectF(0, 0, 860, 460), 14, 14)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#eee9df"))
        painter.drawRoundedRect(QRectF(0, 0, 860, 39), 14, 14)
        painter.drawRect(QRectF(0, 20, 860, 19))
        for x, color in ((19, "#d28d76"), (37, "#d6b56f"), (55, "#829777")):
            painter.setBrush(QColor(color))
            painter.drawEllipse(QRectF(x, 15, 9, 9))
        painter.setPen(QColor("#99958a"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(90, 12, 690, 18), Qt.AlignmentFlag.AlignCenter, "Safe design preview")

        painter.setPen(QPen(QColor("#e7e2d8"), 1))
        painter.drawLine(0, 39, 860, 39)
        painter.setPen(QColor("#53644f"))
        painter.setFont(QFont("Georgia", 15, QFont.Weight.DemiBold))
        painter.drawText(QRectF(28, 54, 500, 28), Qt.AlignmentFlag.AlignLeft, self.prompt_title)
        painter.setPen(QColor("#8c897e"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(28, 84, 180, 17), Qt.AlignmentFlag.AlignLeft, "LIVE BUILD WIREFRAME")

        painter.setPen(QPen(QColor("#e7e2d8"), 1))
        painter.drawLine(190, 111, 190, 420)
        painter.setPen(QColor("#6b7165"))
        painter.setFont(QFont("Segoe UI", 9))
        sidebar_items = ["Overview", "Components", "Files", "Reviews"]
        for index, label in enumerate(sidebar_items):
            y = 132 + index * 36
            painter.setBrush(QColor("#edf0e7") if index == 0 else QColor("#faf8f3"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(18, y - 10, 155, 27), 6, 6)
            painter.setPen(QColor("#53644f") if index == 0 else QColor("#79786e"))
            painter.drawText(QRectF(31, y - 3, 138, 18), Qt.AlignmentFlag.AlignLeft, label)

        content_x = 218
        painter.setPen(QColor("#4c4e44"))
        painter.setFont(QFont("Georgia", 13, QFont.Weight.DemiBold))
        painter.drawText(QRectF(content_x, 113, 580, 25), Qt.AlignmentFlag.AlignLeft, "Project overview")
        painter.setPen(QColor("#969187"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(QRectF(content_x, 140, 600, 20), Qt.AlignmentFlag.AlignLeft, self.status)

        cards = self.components[:3] or ["Plan", "Build", "Review"]
        card_width = 190
        for index, name in enumerate(cards):
            x = content_x + index * 202
            painter.setPen(QPen(QColor("#e6e1d7"), 1))
            painter.setBrush(QColor("#fffdf8"))
            painter.drawRoundedRect(QRectF(x, 174, card_width, 98), 9, 9)
            painter.setPen(QColor("#a28c71"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
            painter.drawText(QRectF(x + 13, 188, card_width - 26, 17), Qt.AlignmentFlag.AlignLeft, f"PART {index + 1}")
            painter.setPen(QColor("#515349"))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            painter.drawText(
                QRectF(x + 13, 211, card_width - 26, 43),
                Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                name,
            )

        painter.setPen(QColor("#4c4e44"))
        painter.setFont(QFont("Georgia", 11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(content_x, 294, 300, 22), Qt.AlignmentFlag.AlignLeft, "Stack & files")
        painter.setPen(QPen(QColor("#e6e1d7"), 1))
        painter.setBrush(QColor("#fffdf8"))
        painter.drawRoundedRect(QRectF(content_x, 320, 610, 88), 9, 9)
        painter.setPen(QColor("#69745f"))
        painter.setFont(QFont("Segoe UI", 9))
        stack = ", ".join(self.dependencies[:4]) or "Waiting for the Architect's stack"
        painter.drawText(QRectF(content_x + 14, 332, 580, 22), Qt.AlignmentFlag.AlignLeft, f"Stack  ·  {stack[:86]}")
        file_summary = ", ".join(self.files[:3]) or "Source tree will appear after design review"
        painter.setPen(QColor("#858277"))
        painter.drawText(
            QRectF(content_x + 14, 359, 580, 34),
            Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
            f"Files  ·  {file_summary[:130]}",
        )

        painter.setPen(QPen(QColor("#e7e2d8"), 1))
        painter.drawLine(0, 424, 860, 424)
        painter.setPen(QColor("#7d8872"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.drawText(QRectF(25, 433, 810, 16), Qt.AlignmentFlag.AlignLeft, f"BUILD PROGRESS  ·  {self.progress}%")
