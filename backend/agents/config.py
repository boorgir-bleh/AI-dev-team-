from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    CYBER_SECURITY = "cyber_security"
    TESTER = "tester"
    DOCUMENTATION = "documentation"
    CRITIC = "critic"


DEFAULT_AGENT_NAMES = {
    AgentRole.ORCHESTRATOR: "Maya",
    AgentRole.ARCHITECT: "Arjun",
    AgentRole.DEVELOPER: "Dev",
    AgentRole.CYBER_SECURITY: "Sana",
    AgentRole.TESTER: "Tara",
    AgentRole.DOCUMENTATION: "Doc",
    AgentRole.CRITIC: "Ojas",
}

DEFAULT_TASK_PROMPTS = {
    AgentRole.ORCHESTRATOR: (
        "Turn the user's request into a testable project specification. "
        "Return goals, assumptions, acceptance criteria, and out-of-scope items.\n\n"
        "Run context (JSON):\n{{context}}"
    ),
    AgentRole.ARCHITECT: (
        "Create a concrete, minimal design from the specification. Include components, "
        "interfaces, a file tree, dependencies, and data flow. Address any review notes.\n\n"
        "Run context (JSON):\n{{context}}"
    ),
    AgentRole.DEVELOPER: (
        "Implement the approved design. Return complete file contents and a concise summary. "
        "Address the supplied review and test reports without expanding scope.\n\n"
        "Run context (JSON):\n{{context}}"
    ),
    AgentRole.CYBER_SECURITY: (
        "Review the supplied design or implementation for security risks. Return concrete "
        "findings with severity and remediation; critical/high findings must fail the gate.\n\n"
        "Run context (JSON):\n{{context}}"
    ),
    AgentRole.TESTER: (
        "Map tests to the acceptance criteria. Report passed and failed counts, failing cases, "
        "and reproducible steps. Do not claim tests were executed unless the context confirms it.\n\n"
        "Run context (JSON):\n{{context}}"
    ),
    AgentRole.DOCUMENTATION: (
        "Write accurate setup, usage, and API documentation from the specification and final "
        "implementation. Do not invent behavior or commands.\n\n"
        "Run context (JSON):\n{{context}}"
    ),
    AgentRole.CRITIC: (
        "Review the supplied design or implementation for quality, maintainability, scope "
        "alignment, and missed requirements. Every REQUEST_CHANGES verdict needs a justified "
        "blocking comment.\n\nRun context (JSON):\n{{context}}"
    ),
}


class AgentPromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    task_prompt: str = Field(min_length=1, max_length=10_000)

    @field_validator("name", "system_prompt", "task_prompt")
    @classmethod
    def reject_blank_values(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized


class AgentConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: dict[AgentRole, AgentPromptConfig]

    @model_validator(mode="after")
    def require_all_roles_and_unique_names(self) -> "AgentConfiguration":
        expected = set(AgentRole)
        actual = set(self.agents)
        missing = expected - actual
        extra = actual - expected
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing roles: {', '.join(sorted(role.value for role in missing))}")
            if extra:
                details.append(f"unexpected roles: {', '.join(sorted(str(role) for role in extra))}")
            raise ValueError("; ".join(details))

        normalized_names = [profile.name.casefold() for profile in self.agents.values()]
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("agent names must be unique")
        return self


@lru_cache(maxsize=1)
def get_default_agent_configuration() -> AgentConfiguration:
    agents = {
        role: AgentPromptConfig(
            name=DEFAULT_AGENT_NAMES[role],
            system_prompt=(PROMPTS_DIR / f"{role.value}.md").read_text(encoding="utf-8"),
            task_prompt=DEFAULT_TASK_PROMPTS[role],
        )
        for role in AgentRole
    }
    return AgentConfiguration(agents=agents)
