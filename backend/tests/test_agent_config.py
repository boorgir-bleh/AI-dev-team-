import unittest

from pydantic import ValidationError

from backend.agents.config import (
    AgentConfiguration,
    AgentRole,
    get_default_agent_configuration,
)


class AgentConfigurationTests(unittest.TestCase):
    def test_defaults_include_every_role_and_editable_prompts(self) -> None:
        configuration = get_default_agent_configuration()

        self.assertEqual(set(configuration.agents), set(AgentRole))
        for profile in configuration.agents.values():
            self.assertTrue(profile.name)
            self.assertTrue(profile.system_prompt)
            self.assertTrue(profile.task_prompt)

    def test_rejects_missing_roles_and_duplicate_names(self) -> None:
        defaults = get_default_agent_configuration().model_dump(mode="json")
        incomplete = {"agents": dict(defaults["agents"])}
        del incomplete["agents"]["tester"]
        with self.assertRaises(ValidationError):
            AgentConfiguration.model_validate(incomplete)

        duplicated = {"agents": dict(defaults["agents"])}
        duplicated["agents"]["architect"] = {
            **duplicated["agents"]["architect"],
            "name": duplicated["agents"]["orchestrator"]["name"],
        }
        with self.assertRaisesRegex(ValidationError, "agent names must be unique"):
            AgentConfiguration.model_validate(duplicated)

    def test_rejects_blank_and_overlong_prompts(self) -> None:
        defaults = get_default_agent_configuration().model_dump(mode="json")
        defaults["agents"]["architect"]["system_prompt"] = " "
        with self.assertRaises(ValidationError):
            AgentConfiguration.model_validate(defaults)

        defaults = get_default_agent_configuration().model_dump(mode="json")
        defaults["agents"]["architect"]["system_prompt"] = "x" * 20_001
        with self.assertRaises(ValidationError):
            AgentConfiguration.model_validate(defaults)


if __name__ == "__main__":
    unittest.main()
