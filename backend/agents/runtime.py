import json
import os
import random
from pathlib import Path
from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from time import sleep
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.exceptions import ModelRateLimitError, OutputParserException
from pydantic import BaseModel, ValidationError

from backend.agents.config import AgentConfiguration, AgentRole, get_default_agent_configuration
from backend.agents.llm_calls import LLMCallObserver, json_safe
from backend.agents.mock import AgentOutputError, MAX_OUTPUT_RETRIES


T = TypeVar("T", bound=BaseModel)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GEMINI_MODEL = "gemini-4-hydrogen"
RATE_LIMIT_RETRY_DELAYS = (1.0, 2.0, 4.0)


class GeminiRateLimitError(RuntimeError):
    pass


class AgentRuntime(Protocol):
    def structured(
        self,
        role: str,
        schema: type[T],
        default: T,
        *,
        context: dict[str, Any] | None = None,
        agent_configuration: dict[str, Any] | AgentConfiguration | None = None,
    ) -> T: ...


class GeminiAgentRuntime:
    def __init__(
        self,
        api_key: str,
        model_name: str = DEFAULT_GEMINI_MODEL,
        on_llm_call: LLMCallObserver | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError(
                "Gemini API key is missing. Set GEMINI_API_KEY in the root .env file."
            )
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError as error:
            raise RuntimeError(
                "Gemini support is not installed. Run python -m pip install -r backend/requirements.txt."
            ) from error

        self.model_name = model_name
        self._on_llm_call = on_llm_call
        self._request_lock = Lock()
        self._model = ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=1.0,
            max_retries=0,
        )

    def structured(
        self,
        role: str,
        schema: type[T],
        default: T,
        *,
        context: dict[str, Any] | None = None,
        agent_configuration: dict[str, Any] | AgentConfiguration | None = None,
    ) -> T:
        del default
        profile_role = {
            "orchestrator_spec": "orchestrator",
            "architect": "architect",
            "developer": "developer",
            "cyber_security": "cyber_security",
            "tester": "tester",
            "documentation": "documentation",
            "critic_design": "critic",
            "critic_code": "critic",
        }.get(role)
        if profile_role is None:
            raise ValueError(f"No system prompt is configured for role '{role}'")

        role_config = (
            AgentConfiguration.model_validate(agent_configuration)
            if agent_configuration is not None
            else get_default_agent_configuration()
        )
        profile = role_config.agents[AgentRole(profile_role)]
        system_prompt = profile.system_prompt.replace("{{agent_name}}", profile.name)
        structured_model = self._model.with_structured_output(schema)
        context_json = json.dumps(context or {}, ensure_ascii=False, indent=2)
        task_prompt = profile.task_prompt.replace("{{agent_name}}", profile.name)
        if "{{context}}" in task_prompt:
            task_prompt = task_prompt.replace("{{context}}", context_json)
        else:
            task_prompt = f"{task_prompt}\n\nRun context (JSON):\n{context_json}"
        failures: list[str] = []

        for attempt in range(1, MAX_OUTPUT_RETRIES + 2):
            retry_note = ""
            if failures:
                retry_note = (
                    "\n\nYour previous response did not match the required schema. "
                    f"Correct these validation errors and return the complete object: {failures[-1]}"
                )
            human_prompt = f"{task_prompt}{retry_note}"
            request = {
                "system": system_prompt,
                "human": human_prompt,
                "schema": schema.model_json_schema(),
            }
            raw_response: Any = None
            parser_failure: OutputParserException | None = None
            rate_limit_attempt = 0
            with self._request_lock:
                while True:
                    rate_limit_attempt += 1
                    call_id = str(uuid4())
                    started = perf_counter()
                    self._record_call(
                        call_id,
                        role,
                        attempt,
                        request,
                        None,
                        None,
                        "pending",
                        "request",
                        started,
                        rate_limit_attempt,
                    )
                    try:
                        raw_response = structured_model.invoke(
                            [
                                ("system", system_prompt),
                                ("human", human_prompt),
                            ]
                        )
                    except ModelRateLimitError as error:
                        retry_index = rate_limit_attempt - 1
                        if retry_index < len(RATE_LIMIT_RETRY_DELAYS):
                            self._record_call(
                                call_id,
                                role,
                                attempt,
                                request,
                                None,
                                str(error),
                                "retrying",
                                "response",
                                started,
                                rate_limit_attempt,
                            )
                            delay = RATE_LIMIT_RETRY_DELAYS[retry_index] + random.uniform(0, 0.5)
                            sleep(delay)
                            continue
                        self._record_call(
                            call_id,
                            role,
                            attempt,
                            request,
                            None,
                            str(error),
                            "error",
                            "response",
                            started,
                            rate_limit_attempt,
                        )
                        raise GeminiRateLimitError(
                            f"Gemini returned HTTP 429 RESOURCE_EXHAUSTED for model "
                            f"'{self.model_name}' after {rate_limit_attempt} attempts. "
                            "Check this model and API key's quota and billing in Google AI Studio, "
                            "or wait for a temporary limit to reset and retry. No fallback model was used."
                        ) from error
                    except OutputParserException as error:
                        parser_failure = error
                        failures.append(str(error))
                        self._record_call(
                            call_id,
                            role,
                            attempt,
                            request,
                            raw_response,
                            str(error),
                            "invalid_output",
                            "response",
                            started,
                            rate_limit_attempt,
                        )
                        break
                    except Exception as error:
                        self._record_call(
                            call_id,
                            role,
                            attempt,
                            request,
                            raw_response,
                            f"{type(error).__name__}: {error}",
                            "error",
                            "response",
                            started,
                            rate_limit_attempt,
                        )
                        raise
                    break
            if parser_failure is not None:
                continue
            try:
                validated = schema.model_validate(raw_response)
            except ValidationError as error:
                failures.append(str(error))
                self._record_call(
                    call_id,
                    role,
                    attempt,
                    request,
                    raw_response,
                    str(error),
                    "invalid_output",
                    "response",
                    started,
                    rate_limit_attempt,
                )
                continue
            self._record_call(
                call_id,
                role,
                attempt,
                request,
                raw_response,
                None,
                "success",
                "response",
                started,
                rate_limit_attempt,
            )
            return validated

        raise AgentOutputError(
            f"{role} returned invalid structured output after {MAX_OUTPUT_RETRIES + 1} attempts: "
            f"{failures[-1]}"
        )

    def _record_call(
        self,
        call_id: str,
        role: str,
        attempt: int,
        request: dict[str, Any],
        response: Any,
        error: str | None,
        status: str,
        phase: str,
        started: float,
        rate_limit_attempt: int = 1,
    ) -> None:
        observer = getattr(self, "_on_llm_call", None)
        if observer is None:
            return
        observer(
            {
                "id": call_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "provider": "gemini",
                "model": self.model_name,
                "role": role,
                "attempt": attempt,
                "rate_limit_attempt": rate_limit_attempt,
                "phase": phase,
                "status": status,
                "duration_ms": round((perf_counter() - started) * 1000),
                "request": request,
                "response": json_safe(response),
                "error": error,
            }
        )


def create_agent_runtime(
    provider: str | None = None,
    *,
    model_name: str | None = None,
    on_llm_call: LLMCallObserver | None = None,
) -> AgentRuntime:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    selected_provider = (provider or os.getenv("DEV_OFFICE_LLM_PROVIDER", "gemini")).strip().lower()
    if selected_provider == "mock":
        from backend.agents.mock import MockLLM

        return MockLLM(on_llm_call=on_llm_call)
    if selected_provider != "gemini":
        raise ValueError("DEV_OFFICE_LLM_PROVIDER must be 'gemini' or 'mock'")

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    selected_model = (
        model_name
        if model_name is not None
        else os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    ).strip()
    if not selected_model:
        raise ValueError("GEMINI_MODEL must not be blank")
    runtime = GeminiAgentRuntime(
        api_key=api_key,
        model_name=selected_model,
        on_llm_call=on_llm_call,
    )
    return runtime
