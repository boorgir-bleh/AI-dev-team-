from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Spec(StrictOutput):
    goals: list[str] = Field(min_length=1)
    assumptions: list[str]
    acceptance_criteria: list[str] = Field(min_length=1)
    out_of_scope: list[str]


class Design(StrictOutput):
    components: list[str] = Field(min_length=1)
    interfaces: list[str] = Field(min_length=1)
    file_tree: list[str] = Field(min_length=1)
    dependencies: list[str]
    data_flow: list[str] = Field(min_length=1)


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SecurityFinding(StrictOutput):
    severity: Severity
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    remediation: str = Field(min_length=1)


class SecurityReport(StrictOutput):
    findings: list[SecurityFinding]
    gate: Literal["PASS", "FAIL"]

    @model_validator(mode="after")
    def critical_findings_fail_gate(self) -> "SecurityReport":
        if self.gate == "PASS" and any(
            finding.severity in (Severity.CRITICAL, Severity.HIGH)
            for finding in self.findings
        ):
            raise ValueError("critical/high findings require a FAIL gate")
        return self


class ReviewComment(StrictOutput):
    priority: Literal["blocking", "major", "minor"]
    comment: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class CriticReport(StrictOutput):
    verdict: Literal["APPROVE", "REQUEST_CHANGES"]
    comments: list[ReviewComment]

    @model_validator(mode="after")
    def changes_need_justified_blocker(self) -> "CriticReport":
        if self.verdict == "REQUEST_CHANGES" and not any(
            comment.priority == "blocking" and comment.rationale.strip()
            for comment in self.comments
        ):
            raise ValueError("REQUEST_CHANGES requires a justified blocking comment")
        return self


class TestReport(StrictOutput):
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    failing_cases: list[str]
    repro_steps: list[str]


class DocumentationReport(StrictOutput):
    files: dict[str, str] = Field(min_length=1)
    summary: str = Field(min_length=1)


class Implementation(StrictOutput):
    files: dict[str, str] = Field(min_length=1)
    summary: str = Field(min_length=1)


class MeetingOutcome(StrictOutput):
    decisions: list[str]
    action_items: list[str]
    blockers: list[str]


class FinalAcceptance(StrictOutput):
    accepted: bool
    status: Literal["completed", "failed"]
    known_issues: list[str]
    summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def status_matches_acceptance(self) -> "FinalAcceptance":
        if self.accepted != (self.status == "completed"):
            raise ValueError("status must match accepted")
        return self
