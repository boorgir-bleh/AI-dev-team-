import json
import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from backend.agents.config import AgentConfiguration, AgentRole
from backend.agents.runtime import create_agent_runtime
from backend.events.schema import EventEnvelope, EventType
from backend.events.store import EventStore
from backend.graph.runner import GraphRunner


LOGGER = logging.getLogger(__name__)


class GraphWorker(QObject):
    event_received = pyqtSignal(dict)
    llm_call_received = pyqtSignal(dict)
    model_ready = pyqtSignal(str, str)
    approval_requested = pyqtSignal(dict)
    run_completed = pyqtSignal(dict)
    run_failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        run_id: str,
        prompt: str,
        approval_required: bool,
        agent_configuration: AgentConfiguration,
        checkpoint_path: Path,
        event_store: EventStore,
        provider: str | None = None,
        model_name: str | None = None,
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.prompt = prompt
        self.approval_required = approval_required
        self.agent_configuration = agent_configuration
        self.checkpoint_path = checkpoint_path
        self.event_store = event_store
        self.provider = provider
        self.model_name = model_name
        self._runner: GraphRunner | None = None

    @pyqtSlot()
    def run(self) -> None:
        try:
            runtime = create_agent_runtime(
                self.provider,
                model_name=self.model_name,
                on_llm_call=self._publish_llm_call,
            )
            provider = "gemini" if hasattr(runtime, "model_name") else "mock"
            model_name = getattr(runtime, "model_name", "scripted mock")
            self.model_ready.emit(provider, model_name)
            self._runner = GraphRunner(self.checkpoint_path, runtime)
            result = self._runner.run(
                self.prompt,
                self.run_id,
                approval_required=self.approval_required,
                agent_configuration=self.agent_configuration,
                on_event=self._publish_event,
            )
            if "__interrupt__" in result:
                self.approval_requested.emit(result)
                return
            self._complete(result)
        except Exception as error:
            self._fail(error)

    @pyqtSlot(bool)
    def resume_approval(self, approved: bool) -> None:
        if self._runner is None:
            self.run_failed.emit("The graph checkpoint is not available for approval.")
            self.finished.emit()
            return
        try:
            result = self._runner.resume_approval(
                self.run_id,
                approved,
                on_event=self._publish_event,
            )
            self._complete(result)
        except Exception as error:
            self._fail(error)

    def _publish_event(self, event_data: dict[str, Any]) -> None:
        event = EventEnvelope.model_validate(event_data)
        self.event_store.append(event)
        self.event_received.emit(event.model_dump(mode="json"))

    def _publish_llm_call(self, call_data: dict[str, Any]) -> None:
        record = dict(call_data)
        record["run_id"] = self.run_id
        call_log = self.event_store.runs_dir / self.run_id / "llm_calls.jsonl"
        call_log.parent.mkdir(parents=True, exist_ok=True)
        with call_log.open("a", encoding="utf-8") as log:
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.llm_call_received.emit(record)

    def _complete(self, result: dict[str, Any]) -> None:
        self.run_completed.emit(result)
        self._close_runner()
        self.finished.emit()

    def _fail(self, error: Exception) -> None:
        LOGGER.exception("DevOffice desktop run %s failed", self.run_id)
        try:
            role = AgentRole.ORCHESTRATOR.value
            name = self.agent_configuration.agents[AgentRole.ORCHESTRATOR].name
            self._publish_event(
                EventEnvelope(
                    run_id=self.run_id,
                    type=EventType.ERROR,
                    agent=name,
                    payload={
                        "agent_role": role,
                        "message": f"The run stopped because {type(error).__name__}: {error}",
                    },
                ).model_dump(mode="json")
            )
        except Exception:
            LOGGER.exception("Could not persist the desktop run error event")
        self.run_failed.emit(f"{type(error).__name__}: {error}")
        self._close_runner()
        self.finished.emit()

    def _close_runner(self) -> None:
        if self._runner is not None:
            self._runner.close()
            self._runner = None
