import sqlite3
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from backend.agents.config import AgentConfiguration
from backend.agents.runtime import AgentRuntime
from backend.graph.workflow import build_workflow, initial_state


class GraphRunner:
    def __init__(
        self,
        database_path: Path,
        llm: AgentRuntime | None = None,
        *,
        max_design_loops: int = 2,
        max_fix_iterations: int = 4,
    ) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, timeout=10, check_same_thread=False)
        self._checkpointer = SqliteSaver(self._connection)
        self._checkpointer.setup()
        self.graph = build_workflow(
            llm,
            max_design_loops=max_design_loops,
            max_fix_iterations=max_fix_iterations,
            checkpointer=self._checkpointer,
        )

    def run(
        self,
        prompt: str,
        run_id: str,
        *,
        approval_required: bool = False,
        agent_configuration: AgentConfiguration | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        state = initial_state(
            prompt,
            run_id,
            approval_required=approval_required,
            agent_configuration=agent_configuration,
        )
        config = self._config(run_id)
        if on_event is None:
            return self.graph.invoke(state, config=config)
        return self._stream(state, config, on_event)

    def resume_approval(
        self,
        run_id: str,
        approved: bool,
        *,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        command = Command(resume=approved)
        config = self._config(run_id)
        if on_event is None:
            return self.graph.invoke(command, config=config)
        return self._stream(command, config, on_event)

    def resume(self, run_id: str) -> dict[str, Any]:
        return self.graph.invoke(None, config=self._config(run_id))

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "GraphRunner":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _stream(
        self,
        graph_input: Any,
        config: dict[str, dict[str, str]],
        on_event: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        interrupts: Any = None
        for update in self.graph.stream(graph_input, config=config, stream_mode="updates"):
            if "__interrupt__" in update:
                interrupts = update["__interrupt__"]
            for node_update in update.values():
                if not isinstance(node_update, dict):
                    continue
                events = node_update.get("events", [])
                if isinstance(events, list):
                    for event in events:
                        if isinstance(event, dict):
                            on_event(event)
        result = dict(self.graph.get_state(config).values)
        if interrupts is not None:
            result["__interrupt__"] = interrupts
        return result

    @staticmethod
    def _config(run_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": run_id}}
