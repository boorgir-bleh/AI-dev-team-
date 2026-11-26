from datetime import datetime, timezone
from collections import defaultdict, deque
from threading import Lock
from time import perf_counter
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from backend.agents.config import AgentConfiguration
from backend.agents.llm_calls import LLMCallObserver, json_safe


T = TypeVar("T", bound=BaseModel)
MAX_OUTPUT_RETRIES = 2


class AgentOutputError(RuntimeError):
    pass


class MockLLM:
    """Deterministic structured-output runtime; scripts can override responses by role."""

    def __init__(
        self,
        scripts: dict[str, list[Any]] | None = None,
        *,
        on_llm_call: LLMCallObserver | None = None,
    ) -> None:
        self._scripts = defaultdict(deque)
        for role, responses in (scripts or {}).items():
            self._scripts[role].extend(responses)
        self._lock = Lock()
        self._on_llm_call = on_llm_call

    def structured(
        self,
        role: str,
        schema: type[T],
        default: T,
        *,
        context: dict[str, Any] | None = None,
        agent_configuration: dict[str, Any] | AgentConfiguration | None = None,
    ) -> T:
        failures: list[str] = []
        with self._lock:
            has_script = bool(self._scripts[role])
            last_raw: Any = None
            for attempt in range(MAX_OUTPUT_RETRIES + 1):
                if self._scripts[role]:
                    last_raw = self._scripts[role].popleft()
                    raw = last_raw
                elif not has_script and attempt == 0:
                    raw = default.model_dump(mode="json")
                    last_raw = raw
                elif last_raw is not None:
                    raw = last_raw
                else:
                    break
                started = perf_counter()
                request = {
                    "mode": "mock",
                    "note": "No API request is made in mock mode; this is the structured context provided to the mock runtime.",
                    "role": role,
                    "context": context or {},
                    "agent_configuration": json_safe(agent_configuration),
                    "schema": schema.model_json_schema(),
                }
                call_id = str(uuid4())
                self._record_call(
                    call_id,
                    attempt + 1,
                    request,
                    None,
                    None,
                    "pending",
                    "request",
                    started,
                )
                try:
                    result = schema.model_validate(raw)
                except ValidationError as error:
                    failures.append(str(error))
                    self._record_call(
                        call_id,
                        attempt + 1,
                        request,
                        raw,
                        str(error),
                        "invalid_output",
                        "response",
                        started,
                    )
                    continue
                self._record_call(
                    call_id,
                    attempt + 1,
                    request,
                    raw,
                    None,
                    "success",
                    "response",
                    started,
                )
                return result

        raise AgentOutputError(
            f"{role} returned invalid structured output after "
            f"{len(failures)} attempt(s): {'; '.join(failures)}"
        )

    def _record_call(
        self,
        call_id: str,
        attempt: int,
        request: dict[str, Any],
        response: Any,
        error: str | None,
        status: str,
        phase: str,
        started: float,
    ) -> None:
        if self._on_llm_call is None:
            return
        self._on_llm_call(
            {
                "id": call_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "provider": "mock",
                "model": "scripted mock",
                "role": request["role"],
                "attempt": attempt,
                "phase": phase,
                "status": status,
                "duration_ms": round((perf_counter() - started) * 1000),
                "request": request,
                "response": json_safe(response),
                "error": error,
            }
        )
