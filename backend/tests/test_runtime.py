import os
from threading import Lock
from typing import Any
from unittest import TestCase
from unittest.mock import patch

from pydantic import BaseModel, Field
from langchain_google_genai.chat_models import GoogleRateLimitError

from backend.agents.config import get_default_agent_configuration
from backend.agents.mock import MockLLM
from backend.agents.runtime import (
    RATE_LIMIT_RETRY_DELAYS,
    GeminiRateLimitError,
    GeminiAgentRuntime,
    create_agent_runtime,
)


class Output(BaseModel):
    value: str = Field(min_length=1)


class FakeStructuredModel:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.messages: list[object] = []

    def invoke(self, messages: list[object]) -> object:
        self.messages.append(messages)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return output


class FakeGeminiModel:
    def __init__(self, outputs: list[object]) -> None:
        self.structured_model = FakeStructuredModel(outputs)
        self.schema: type[BaseModel] | None = None

    def with_structured_output(self, schema: type[BaseModel]) -> FakeStructuredModel:
        self.schema = schema
        return self.structured_model


class GeminiRuntimeTests(TestCase):
    def test_runtime_requires_api_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
            GeminiAgentRuntime("")

    def test_runtime_configures_provider_without_exposing_key(self) -> None:
        with patch("langchain_google_genai.ChatGoogleGenerativeAI") as model_factory:
            runtime = GeminiAgentRuntime("local-test-key", "gemini-test")

        model_factory.assert_called_once_with(
            model="gemini-test",
            api_key="local-test-key",
            temperature=1.0,
            max_retries=0,
        )
        self.assertEqual(runtime.model_name, "gemini-test")

    def test_runtime_retries_schema_errors_and_returns_validated_output(self) -> None:
        fake_model = FakeGeminiModel(
            [
                {"value": ""},
                {"value": "validated"},
            ]
        )
        runtime = GeminiAgentRuntime.__new__(GeminiAgentRuntime)
        runtime.model_name = "test-model"
        runtime._model = fake_model
        runtime._request_lock = Lock()
        call_records: list[dict[str, Any]] = []
        runtime._on_llm_call = call_records.append
        result = runtime.structured(
            "orchestrator_spec",
            Output,
            Output(value="mock"),
            context={"user_prompt": "test"},
        )

        self.assertEqual(result.value, "validated")
        self.assertEqual(len(fake_model.structured_model.messages), 2)
        self.assertIn("test", str(fake_model.structured_model.messages[-1]))
        self.assertIs(fake_model.schema, Output)
        response_records = [call for call in call_records if call["phase"] == "response"]
        self.assertEqual(
            [call["status"] for call in response_records],
            ["invalid_output", "success"],
        )
        self.assertEqual([call["attempt"] for call in response_records], [1, 2])
        self.assertEqual(response_records[0]["response"], {"value": ""})
        self.assertIn("Run context", call_records[0]["request"]["human"])
        self.assertEqual(response_records[1]["response"], {"value": "validated"})
        self.assertEqual(call_records[0]["phase"], "request")

    def test_runtime_uses_custom_system_and_task_prompts(self) -> None:
        fake_model = FakeGeminiModel([{"value": "validated"}])
        runtime = GeminiAgentRuntime.__new__(GeminiAgentRuntime)
        runtime.model_name = "test-model"
        runtime._model = fake_model
        runtime._request_lock = Lock()
        configuration = get_default_agent_configuration().model_dump(mode="json")
        configuration["agents"]["orchestrator"].update(
            {
                "name": "Coordinator",
                "system_prompt": "You are {{agent_name}}. Follow the custom system prompt.",
                "task_prompt": "Process {{context}} as {{agent_name}}.",
            }
        )

        runtime.structured(
            "orchestrator_spec",
            Output,
            Output(value="mock"),
            context={"request": "build a tool"},
            agent_configuration=configuration,
        )

        messages = fake_model.structured_model.messages[0]
        self.assertEqual(messages[0][1], "You are Coordinator. Follow the custom system prompt.")
        self.assertIn("Process", messages[1][1])
        self.assertIn("Coordinator", messages[1][1])
        self.assertIn("build a tool", messages[1][1])

    def test_runtime_retries_rate_limit_and_records_each_attempt(self) -> None:
        fake_model = FakeGeminiModel(
            [
                GoogleRateLimitError("RESOURCE_EXHAUSTED"),
                {"value": "recovered"},
            ]
        )
        runtime = GeminiAgentRuntime.__new__(GeminiAgentRuntime)
        runtime.model_name = "test-model"
        runtime._model = fake_model
        runtime._request_lock = Lock()
        call_records: list[dict[str, Any]] = []
        runtime._on_llm_call = call_records.append

        with (
            patch("backend.agents.runtime.sleep") as wait,
            patch("backend.agents.runtime.random.uniform", return_value=0),
        ):
            result = runtime.structured(
                "orchestrator_spec",
                Output,
                Output(value="mock"),
            )

        self.assertEqual(result.value, "recovered")
        wait.assert_called_once_with(RATE_LIMIT_RETRY_DELAYS[0])
        self.assertEqual(len(fake_model.structured_model.messages), 2)
        self.assertEqual(
            [call["status"] for call in call_records if call["phase"] == "response"],
            ["retrying", "success"],
        )
        self.assertNotEqual(call_records[0]["id"], call_records[2]["id"])

    def test_runtime_surfaces_exhausted_rate_limit_with_quota_guidance(self) -> None:
        fake_model = FakeGeminiModel(
            [GoogleRateLimitError("RESOURCE_EXHAUSTED") for _ in range(len(RATE_LIMIT_RETRY_DELAYS) + 1)]
        )
        runtime = GeminiAgentRuntime.__new__(GeminiAgentRuntime)
        runtime.model_name = "test-model"
        runtime._model = fake_model
        runtime._request_lock = Lock()
        call_records: list[dict[str, Any]] = []
        runtime._on_llm_call = call_records.append

        with (
            patch("backend.agents.runtime.sleep"),
            patch("backend.agents.runtime.random.uniform", return_value=0),
            self.assertRaisesRegex(GeminiRateLimitError, "quota and billing"),
        ):
            runtime.structured("orchestrator_spec", Output, Output(value="mock"))

        self.assertEqual(len(fake_model.structured_model.messages), len(RATE_LIMIT_RETRY_DELAYS) + 1)
        self.assertEqual(call_records[-1]["status"], "error")

    def test_factory_keeps_mock_mode_available(self) -> None:
        with patch.dict(os.environ, {"DEV_OFFICE_LLM_PROVIDER": "mock"}, clear=False):
            self.assertIsInstance(create_agent_runtime(), MockLLM)

    def test_factory_applies_selected_model_and_records_mock_calls(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "DEV_OFFICE_LLM_PROVIDER": "gemini",
                    "GEMINI_API_KEY": "local-test-key",
                },
                clear=False,
            ),
            patch("langchain_google_genai.ChatGoogleGenerativeAI") as model_factory,
        ):
            runtime = create_agent_runtime(model_name="selected-model")
        model_factory.assert_called_once_with(
            model="selected-model",
            api_key="local-test-key",
            temperature=1.0,
            max_retries=0,
        )
        self.assertEqual(runtime.model_name, "selected-model")

        calls: list[dict[str, Any]] = []
        mock = MockLLM(on_llm_call=calls.append)
        mock.structured("tester", Output, Output(value="mock result"), context={"test": True})
        self.assertEqual(calls[0]["provider"], "mock")
        self.assertEqual(calls[0]["phase"], "request")
        self.assertEqual(calls[-1]["response"], {"value": "mock result"})
        self.assertEqual(calls[-1]["request"]["context"], {"test": True})
