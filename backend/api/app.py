import asyncio
import logging
import os
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError, field_validator
from dotenv import load_dotenv

from backend.agents.config import AgentConfiguration, AgentRole, get_default_agent_configuration
from backend.agents.runtime import AgentRuntime, GeminiAgentRuntime, create_agent_runtime
from backend.events.schema import EventEnvelope, EventInput
from backend.events.service import EventService
from backend.events.store import EventStore
from backend.graph.runner import GraphRunner
from backend.tools.rooms import (
    BookingConflictError,
    BookingRequest,
    RoomBooking,
    RoomBookingService,
    RoomSchedule,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=False)
RUNS_DIR = Path(os.environ.get("DEV_OFFICE_RUNS_DIR", PROJECT_ROOT / "runs")).resolve()
DEFAULT_EVENT_SERVICE = EventService(
    EventStore(RUNS_DIR / "events.sqlite3", RUNS_DIR),
)
DEFAULT_ROOM_BOOKING_SERVICE = RoomBookingService(RUNS_DIR / "rooms.sqlite3")
LOGGER = logging.getLogger(__name__)


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    approval_required: bool = False
    agent_configuration: AgentConfiguration = Field(default_factory=get_default_agent_configuration)

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prompt must not be blank")
        return value.strip()


class RunResponse(BaseModel):
    run_id: str
    status: str
    provider: str
    model: str


def create_app(
    event_service: EventService | None = None,
    room_booking_service: RoomBookingService | None = None,
    checkpoint_path: Path | None = None,
) -> FastAPI:
    service = event_service or DEFAULT_EVENT_SERVICE
    bookings = room_booking_service or DEFAULT_ROOM_BOOKING_SERVICE
    graph_database_path = checkpoint_path or RUNS_DIR / "checkpoints.sqlite3"
    app = FastAPI(title="DevOffice Events API", version="0.1.0")
    app.state.event_service = service
    app.state.room_booking_service = bookings
    app.state.checkpoint_path = graph_database_path

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/agents/config", response_model=AgentConfiguration)
    async def get_agent_configuration() -> AgentConfiguration:
        return get_default_agent_configuration()

    @app.post("/api/runs", response_model=RunResponse, status_code=202)
    async def start_run(request: RunRequest, background_tasks: BackgroundTasks) -> RunResponse:
        try:
            runtime = create_agent_runtime()
        except ValueError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        provider = "gemini" if isinstance(runtime, GeminiAgentRuntime) else "mock"
        model_name = runtime.model_name if isinstance(runtime, GeminiAgentRuntime) else "scripted mock"
        run_id = str(uuid4())
        background_tasks.add_task(
            execute_run,
            run_id,
            request.prompt,
            request.approval_required,
            request.agent_configuration,
            runtime,
            graph_database_path,
            service,
        )
        return RunResponse(run_id=run_id, status="running", provider=provider, model=model_name)

    @app.post("/api/runs/{run_id}/events", response_model=EventEnvelope, status_code=201)
    async def create_event(run_id: str, event_input: EventInput) -> EventEnvelope:
        try:
            event = EventEnvelope(run_id=run_id, **event_input.model_dump())
            return await service.publish(event)
        except ValidationError as error:
            raise HTTPException(status_code=422, detail=error.errors()) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/runs/{run_id}/events", response_model=list[EventEnvelope])
    async def replay_events(
        run_id: str,
        after: str | None = Query(default=None, description="Event ID to continue after"),
    ) -> list[EventEnvelope]:
        try:
            return service.store.replay(run_id, after)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/rooms", response_model=list[RoomSchedule])
    async def list_rooms() -> list[RoomSchedule]:
        return bookings.list_rooms()

    @app.post("/api/rooms/{room_id}/bookings", response_model=RoomBooking, status_code=201)
    async def book_room(room_id: str, request: BookingRequest) -> RoomBooking:
        try:
            booking = bookings.book_room(
                room_id=room_id,
                organizer=request.organizer,
                attendees=request.attendees,
                topic=request.topic,
                duration_minutes=request.duration_minutes,
                starts_at=request.starts_at,
            )
        except BookingConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        await service.publish(
            EventEnvelope(
                run_id="office",
                type="room_booked",
                agent=booking.organizer,
                room=booking.room_id,
                payload=booking.model_dump(mode="json"),
            )
        )
        return booking

    @app.delete("/api/rooms/bookings/{booking_id}", response_model=RoomBooking)
    async def release_room(booking_id: str, released_by: str = Query(min_length=1, max_length=80)) -> RoomBooking:
        try:
            booking = bookings.release_room(booking_id, released_by)
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

        await service.publish(
            EventEnvelope(
                run_id="office",
                type="room_released",
                agent=booking.organizer,
                room=booking.room_id,
                payload=booking.model_dump(mode="json"),
            )
        )
        return booking

    @app.websocket("/ws/{run_id}")
    async def stream_events(
        websocket: WebSocket,
        run_id: str,
        after: str | None = None,
    ) -> None:
        try:
            service.store._validate_run_id(run_id)
        except ValueError:
            await websocket.close(code=1008, reason="Invalid run ID")
            return

        await websocket.accept()
        queue = await service.broker.subscribe(run_id)
        try:
            high_water, replay = service.store.snapshot(run_id, after)
            for stored_event in replay:
                await websocket.send_json(stored_event.event.model_dump(mode="json"))

            while True:
                stored_event = await queue.get()
                if stored_event is None:
                    await websocket.close(code=1013, reason="Client is too slow; reconnect to replay")
                    return
                if stored_event.sequence > high_water:
                    await websocket.send_json(stored_event.event.model_dump(mode="json"))
        except ValueError as error:
            await websocket.close(code=1008, reason=str(error))
        except WebSocketDisconnect:
            pass
        finally:
            await service.broker.unsubscribe(run_id, queue)

    return app


async def execute_run(
    run_id: str,
    prompt: str,
    approval_required: bool,
    agent_configuration: AgentConfiguration,
    runtime: AgentRuntime,
    checkpoint_path: Path,
    event_service: EventService,
) -> None:
    event_loop = asyncio.get_running_loop()

    def publish_from_graph_thread(event_data: dict[str, object]) -> None:
        event = EventEnvelope.model_validate(event_data)
        future = asyncio.run_coroutine_threadsafe(event_service.publish(event), event_loop)
        future.result()

    def run_graph() -> None:
        with GraphRunner(checkpoint_path, runtime) as runner:
            runner.run(
                prompt,
                run_id,
                approval_required=approval_required,
                agent_configuration=agent_configuration,
                on_event=publish_from_graph_thread,
            )

    try:
        await asyncio.to_thread(run_graph)
    except Exception as error:
        LOGGER.exception("DevOffice run %s failed", run_id)
        await event_service.publish(
            EventEnvelope(
                run_id=run_id,
                type="error",
                agent=agent_configuration.agents[AgentRole.ORCHESTRATOR].name,
                payload={
                    "agent_role": AgentRole.ORCHESTRATOR.value,
                    "message": f"The run stopped because {type(error).__name__}. Check the backend log for details."
                },
            )
        )


app = create_app()
