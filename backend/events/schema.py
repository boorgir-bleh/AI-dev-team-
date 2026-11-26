from datetime import datetime, timezone
from enum import StrEnum
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class EventType(StrEnum):
    AGENT_STATUS = "agent_status"
    AGENT_MOVE = "agent_move"
    ROOM_BOOKED = "room_booked"
    ROOM_RELEASED = "room_released"
    MEETING_STARTED = "meeting_started"
    MEETING_MESSAGE = "meeting_message"
    MEETING_ENDED = "meeting_ended"
    ARTIFACT_CREATED = "artifact_created"
    REVIEW_VERDICT = "review_verdict"
    TEST_RESULT = "test_result"
    SECURITY_FINDING = "security_finding"
    LOOP_ITERATION = "loop_iteration"
    MILESTONE_UPDATE = "milestone_update"
    ERROR = "error"
    RUN_COMPLETE = "run_complete"


class EventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EventType
    agent: str | None = Field(default=None, min_length=1, max_length=80)
    room: str | None = Field(default=None, min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventEnvelope(EventInput):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not RUN_ID_PATTERN.fullmatch(value):
            raise ValueError("run_id must contain 1-64 letters, digits, underscores, or hyphens")
        return value

    @field_validator("ts")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("ts must include a timezone")
        return value
