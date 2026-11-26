from math import cos, sin, tau
from typing import Any

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

from backend.agents.config import AgentConfiguration, AgentRole


AGENT_ROLES = tuple(role.value for role in AgentRole)
AGENT_COLORS = {
    "orchestrator": "#66856b",
    "architect": "#82739a",
    "developer": "#bd785d",
    "cyber_security": "#9b6e72",
    "tester": "#ae8c4c",
    "documentation": "#628391",
    "critic": "#947a59",
}
DESKS = {
    "orchestrator": QPointF(120, 102),
    "architect": QPointF(325, 102),
    "developer": QPointF(530, 102),
    "cyber_security": QPointF(735, 102),
    "tester": QPointF(220, 207),
    "documentation": QPointF(425, 207),
    "critic": QPointF(630, 207),
}
ROOMS = (
    ("whiteboard_room", "Whiteboard Room", QRectF(35, 330, 240, 126), "#7c9a83"),
    ("war_room", "War Room", QRectF(320, 330, 240, 126), "#c27a5c"),
    ("focus_room", "Focus Room", QRectF(605, 330, 240, 126), "#8d82a6"),
)


class OfficeWidget(QWidget):
    agent_selected = pyqtSignal(str)

    def __init__(self, configuration: AgentConfiguration) -> None:
        super().__init__()
        self.setMinimumSize(680, 390)
        self.setMouseTracking(True)
        self.configuration = configuration
        self.selected_role = AgentRole.ORCHESTRATOR.value
        self.positions = {
            role: QPointF(point.x(), point.y() + 40)
            for role, point in DESKS.items()
        }
        self.targets = {role: QPointF(point) for role, point in self.positions.items()}
        self.bookings: dict[str, set[str]] = {}
        self.latest_message = ""
        self.speed = 1.0
        self._active_status: dict[str, str] = {}

    def set_configuration(self, configuration: AgentConfiguration) -> None:
        self.configuration = configuration
        self._update_targets()
        self.update()

    def reset(self) -> None:
        self.bookings.clear()
        self.latest_message = ""
        self._active_status.clear()
        self.positions = {
            role: QPointF(point.x(), point.y() + 40)
            for role, point in DESKS.items()
        }
        self.targets = {role: QPointF(point) for role, point in self.positions.items()}
        self.update()

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.25, min(speed, 4.0))

    def set_bookings(self, bookings: dict[str, list[str]]) -> None:
        self.bookings = {
            room_id: set(attendees)
            for room, attendees in bookings.items()
            if (room_id := self._room_id_from_event({"room": room})) is not None
        }
        self._update_targets()
        self.update()

    def set_selected_agent(self, role: str) -> None:
        if role in self.positions:
            self.selected_role = role
            self.update()

    def apply_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        payload = event.get("payload", {})
        role = payload.get("agent_role")
        if role in AGENT_ROLES and event_type == "agent_status":
            self._active_status[role] = str(payload.get("activity", "working"))
        elif role in AGENT_ROLES and event_type == "agent_move":
            self._active_status[role] = "moving"
        if event_type == "room_booked":
            room_id = self._room_id_from_event(event)
            attendees = payload.get("attendees", [])
            if not attendees:
                attendees = [event.get("agent")]
            if room_id is not None:
                self.bookings[room_id] = {str(name) for name in attendees if name}
        elif event_type == "room_released":
            room_id = self._room_id_from_event(event)
            if room_id is not None:
                self.bookings.pop(room_id, None)
        elif event_type == "meeting_ended":
            self.latest_message = ""
        elif event_type == "meeting_message":
            self.latest_message = str(payload.get("text", ""))[:100]
        if event_type in ("room_booked", "room_released", "meeting_ended"):
            self._update_targets()
        self.update()

    def tick(self) -> None:
        changed = False
        for role, target in self.targets.items():
            current = self.positions[role]
            dx = target.x() - current.x()
            dy = target.y() - current.y()
            if abs(dx) > 0.3 or abs(dy) > 0.3:
                factor = min(0.18 * self.speed, 1.0)
                self.positions[role] = QPointF(current.x() + dx * factor, current.y() + dy * factor)
                changed = True
            else:
                self.positions[role] = QPointF(target)
        if changed:
            self.update()

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setClipRegion(event.region())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 880, self.height() / 510)
        painter.fillRect(QRectF(0, 0, 880, 510), QColor("#eee8dc"))
        painter.setPen(QPen(QColor("#e4ddd0"), 1))
        for y in range(55, 510, 56):
            painter.drawLine(0, y, 880, y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e1d9cb"))
        for x, y in ((9, 12), (39, 34), (63, 8), (14, 47), (74, 44), (50, 20)):
            for offset in range(0, 510, 56):
                painter.drawEllipse(QPointF(x, y + offset), 0.8, 0.8)
        painter.setPen(QPen(QColor("#ded5c7"), 1))
        painter.setBrush(QColor("#f3eee4"))
        painter.drawRoundedRect(QRectF(22, 23, 836, 274), 18, 18)
        self._draw_text(painter, QRectF(44, 30, 200, 22), "OPEN PLAN", "#9d8a72", 9, True)
        self._draw_text(painter, QRectF(700, 30, 134, 22), "7 DESKS · 1 TEAM", "#9b978c", 8)
        painter.setPen(QPen(QColor("#e4ddd0"), 1))
        painter.drawLine(37, 67, 843, 67)

        for role, position in DESKS.items():
            painter.setPen(QPen(QColor("#b99b7c"), 1))
            painter.setBrush(QColor("#d6b99b"))
            painter.drawRoundedRect(QRectF(position.x() - 39, position.y() - 24, 78, 60), 8, 8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#3c4842"))
            painter.drawRoundedRect(QRectF(position.x() - 21, position.y() - 14, 42, 26), 4, 4)
            painter.setBrush(QColor("#d5e0d1"))
            painter.drawRoundedRect(QRectF(position.x() - 17, position.y() - 10, 34, 18), 2, 2)
            painter.setPen(QPen(QColor("#b18c6a"), 3))
            painter.drawLine(
                QPointF(position.x() - 15, position.y() + 22),
                QPointF(position.x() + 15, position.y() + 22),
            )
            painter.setPen(QPen(QColor("#b99b7c"), 1))
            painter.setBrush(QColor("#fbf8f1"))
            painter.drawEllipse(QPointF(position.x() + 29, position.y() - 12), 5, 5)
            name = self.configuration.agents[AgentRole(role)].name
            self._draw_text(
                painter,
                QRectF(position.x() - 83, position.y() + 72, 166, 22),
                name,
                "#6a6358",
                10,
                True,
            )

        self._draw_plant(painter, 52, 252)
        self._draw_plant(painter, 803, 252)
        painter.setPen(QPen(QColor("#d8cebd"), 1))
        painter.setBrush(QColor("#e9e1d4"))
        painter.drawRoundedRect(QRectF(34, 309, 812, 166), 18, 18)
        self._draw_text(painter, QRectF(53, 310, 260, 20), "MEETING ROOMS", "#9d8a72", 9, True)
        for room_id, room_name, rect, accent in ROOMS:
            active = room_id in self.bookings
            painter.setPen(QPen(QColor(accent if active else "#d6cbbb"), 2 if active else 1))
            painter.setBrush(QColor("#fcfaf5" if active else "#f5f0e7"))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(accent))
            painter.drawRoundedRect(QRectF(rect.x() + 12, rect.y() + 12, 5, 20), 2, 2)
            self._draw_text(
                painter,
                QRectF(rect.x() + 129, rect.y() + 10, 101, 24),
                "IN USE" if active else "AVAILABLE",
                "#8b806e",
                7,
                True,
            )
            self._draw_text(
                painter,
                QRectF(rect.x() + 25, rect.y() + 7, 126, 28),
                room_name,
                "#555448",
                11,
                True,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#d5c3a9"))
            painter.drawRoundedRect(
                QRectF(rect.x() + 38, rect.y() + 53, rect.width() - 76, 43),
                20,
                20,
            )
            painter.setBrush(QColor("#8d9b83"))
            painter.setOpacity(0.8)
            painter.drawRoundedRect(
                QRectF(rect.x() + 56, rect.y() + 65, rect.width() - 112, 21),
                10,
                10,
            )
            painter.setOpacity(1)
            if active:
                self._draw_text(
                    painter,
                    QRectF(rect.x() + 17, rect.y() + 98, rect.width() - 34, 18),
                    ", ".join(sorted(self.bookings[room_id]))[:42],
                    "#8d7964",
                    7,
                )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#dfd5c5"))
        painter.drawRoundedRect(QRectF(36, 483, 810, 15), 8, 8)
        painter.setBrush(QColor("#c17d61"))
        painter.drawEllipse(QPointF(64, 490.5), 4, 4)
        self._draw_text(painter, QRectF(74, 483, 106, 15), "COFFEE CORNER", "#736958", 7, True)
        painter.setPen(QPen(QColor("#a99b88"), 2))
        painter.drawLine(QPointF(181, 487), QPointF(181, 494))
        painter.drawLine(QPointF(186, 487), QPointF(186, 494))
        self._draw_text(painter, QRectF(194, 483, 320, 15), "Fresh pot, if you get there before Dev.", "#736958", 8)
        self._draw_people(painter)
        if self.latest_message:
            painter.setPen(QPen(QColor("#d8cebd"), 1))
            painter.setBrush(QColor("#fffdf8"))
            painter.drawRoundedRect(QRectF(250, 286, 380, 30), 15, 15)
            self._draw_text(
                painter,
                QRectF(260, 287, 360, 28),
                f"“{self.latest_message[:68]}”",
                "#55554b",
                9,
            )

    def mousePressEvent(self, event: Any) -> None:
        x = event.position().x() * 880 / max(self.width(), 1)
        y = event.position().y() * 510 / max(self.height(), 1)
        for role, point in self.positions.items():
            if (point.x() - x) ** 2 + (point.y() - y) ** 2 <= 25 ** 2:
                self.selected_role = role
                self.agent_selected.emit(role)
                self.update()
                return
        super().mousePressEvent(event)

    def _draw_people(self, painter: QPainter) -> None:
        for role, position in self.positions.items():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#615b50"))
            painter.setOpacity(0.16)
            painter.drawEllipse(QPointF(position.x(), position.y() + 29), 13, 5)
            painter.setOpacity(1)
            painter.setBrush(QColor(AGENT_COLORS[role]))
            painter.drawRoundedRect(QRectF(position.x() - 12, position.y() + 11, 24, 20), 8, 8)
            painter.setBrush(QColor("#f1c8a9"))
            painter.setPen(QPen(QColor("#a7795b"), 1))
            painter.drawEllipse(QPointF(position.x(), position.y()), 10, 10)
            hair = QPainterPath()
            hair.moveTo(position.x() - 9, position.y() - 2)
            hair.quadTo(position.x() - 8, position.y() - 14, position.x() + 1, position.y() - 11)
            hair.quadTo(position.x() + 10, position.y() - 12, position.x() + 10, position.y() - 1)
            hair.quadTo(position.x() + 2, position.y() - 6, position.x() - 9, position.y() - 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#51443d"))
            painter.drawPath(hair)
            painter.setBrush(QColor("#473e39"))
            painter.drawEllipse(QPointF(position.x() - 3, position.y() + 1), 0.8, 0.8)
            painter.drawEllipse(QPointF(position.x() + 3, position.y() + 1), 0.8, 0.8)
            if role == self.selected_role:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor("#516c54"), 1.5, Qt.PenStyle.DashLine))
                painter.drawEllipse(QPointF(position.x(), position.y()), 15, 15)
            activity = self._active_status.get(role, "")
            if activity and role not in self._attending_roles():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#6f8e71"))
                for dot_x, dot_y in ((-5, -12), (0, -15), (5, -12)):
                    painter.drawEllipse(QPointF(position.x() + dot_x, position.y() + dot_y), 2, 2)

    def _update_targets(self) -> None:
        for role in AGENT_ROLES:
            self.targets[role] = QPointF(DESKS[role].x(), DESKS[role].y() + 40)
        for room_id, attendees in self.bookings.items():
            room = next((entry for entry in ROOMS if entry[0] == room_id), None)
            if room is None:
                continue
            rect = room[2]
            for role in AGENT_ROLES:
                name = self.configuration.agents[AgentRole(role)].name
                if name in attendees:
                    index = sorted(attendees).index(name)
                    angle = -1.5708 + tau * index / max(len(attendees), 1)
                    self.targets[role] = QPointF(
                        rect.center().x() + cos(angle) * 70,
                        rect.y() + 82 + sin(angle) * 27,
                    )

    def _attending_roles(self) -> set[str]:
        return {
            role
            for role in AGENT_ROLES
            if self.configuration.agents[AgentRole(role)].name
            in set().union(*self.bookings.values())
        } if self.bookings else set()

    @staticmethod
    def _draw_plant(painter: QPainter, x: float, y: float) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#bd8568"))
        painter.drawPolygon(
            QPolygonF(
                [
                    QPointF(x, y + 14),
                    QPointF(x + 25, y + 14),
                    QPointF(x + 22, y + 34),
                    QPointF(x + 3, y + 34),
                ]
            )
        )
        painter.setBrush(QColor("#7d987c"))
        for points in (
            (QPointF(x + 12, y + 16), QPointF(x + 4, y + 4), QPointF(x + 5, y - 8)),
            (QPointF(x + 13, y + 15), QPointF(x + 16, y - 2), QPointF(x + 28, y - 8)),
            (QPointF(x + 12, y + 16), QPointF(x + 11, y + 1), QPointF(x + 20, y - 12)),
        ):
            path = QPainterPath(points[0])
            path.quadTo(points[1], points[2])
            path.quadTo(
                QPointF(points[1].x() - 2, points[1].y() + 7),
                points[0],
            )
            painter.drawPath(path)

    @staticmethod
    def _room_id_from_event(event: dict[str, Any]) -> str | None:
        room = event.get("room")
        return next((room_id for room_id, room_name, _, _ in ROOMS if room in (room_id, room_name)), None)

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        color: str,
        size: int,
        bold: bool = False,
    ) -> None:
        painter.setPen(QColor(color))
        painter.setFont(QFont("Segoe UI", size, QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
