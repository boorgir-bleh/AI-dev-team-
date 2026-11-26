import re
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.agents.config import (
    AgentConfiguration,
    DEFAULT_AGENT_NAMES,
    get_default_agent_configuration,
)
from backend.agents.mock import MockLLM
from backend.agents.runtime import AgentRuntime
from backend.agents.schemas import (
    CriticReport,
    Design,
    DocumentationReport,
    FinalAcceptance,
    Implementation,
    SecurityReport,
    Spec,
    TestReport,
)
from backend.events.schema import EventEnvelope, EventType, RUN_ID_PATTERN
from backend.graph.state import OfficeState


MAX_DESIGN_LOOPS = 2
MAX_FIX_ITERATIONS = 4
AGENT_NAMES = {
    role.value: name for role, name in DEFAULT_AGENT_NAMES.items()
}
DEFAULT_AGENT_NAME_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(name) for name in AGENT_NAMES.values()) + r")\b"
)


def initial_state(
    prompt: str,
    run_id: str,
    *,
    approval_required: bool = False,
    agent_configuration: AgentConfiguration | None = None,
) -> OfficeState:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain 1-64 letters, digits, underscores, or hyphens")
    if not prompt.strip():
        raise ValueError("prompt must not be blank")
    return {
        "run_id": run_id,
        "prompt": prompt.strip(),
        "agent_configuration": (
            agent_configuration or get_default_agent_configuration()
        ).model_dump(mode="json"),
        "approval_required": approval_required,
        "spec_approved": not approval_required,
        "design_iterations": 0,
        "fix_iterations": 0,
        "events": [],
    }


def build_workflow(
    llm: AgentRuntime | None = None,
    *,
    max_design_loops: int = MAX_DESIGN_LOOPS,
    max_fix_iterations: int = MAX_FIX_ITERATIONS,
    checkpointer: BaseCheckpointSaver | None = None,
):
    if max_design_loops < 0 or max_fix_iterations < 0:
        raise ValueError("iteration limits must not be negative")
    agent_runtime = llm or MockLLM()

    def emit(
        state: OfficeState,
        event_type: EventType,
        agent: str | None,
        payload: dict[str, Any],
        room: str | None = None,
    ) -> dict[str, Any]:
        event_payload = dict(payload)
        if agent is not None:
            for role, default_name in AGENT_NAMES.items():
                if default_name == agent:
                    agent = state["agent_configuration"]["agents"][role]["name"]
                    event_payload.setdefault("agent_role", role)
                    break
        if event_type == EventType.MILESTONE_UPDATE:
            message = event_payload.get("message")
            if isinstance(message, str):
                configured_names = {
                    default_name: state["agent_configuration"]["agents"][role]["name"]
                    for role, default_name in AGENT_NAMES.items()
                }
                event_payload["message"] = DEFAULT_AGENT_NAME_PATTERN.sub(
                    lambda match: configured_names[match.group(0)],
                    message,
                )
        event = EventEnvelope(
            run_id=state["run_id"],
            type=event_type,
            agent=agent,
            room=room,
            payload=event_payload,
        )
        return event.model_dump(mode="json")

    def orchestrator_spec(state: OfficeState) -> dict[str, Any]:
        prompt = state["prompt"]
        spec = agent_runtime.structured(
            "orchestrator_spec",
            Spec,
            Spec(
                goals=[prompt],
                assumptions=["The user expects a working, locally runnable tool."],
                acceptance_criteria=[
                    "The implementation fulfills the requested behavior.",
                    "Documented tests cover the requested behavior.",
                ],
                out_of_scope=["Features not requested in the prompt."],
            ),
            context={"user_prompt": prompt},
            agent_configuration=state["agent_configuration"],
        )
        return {
            "spec": spec.model_dump(mode="json"),
            "events": [
                emit(
                    state,
                    EventType.ARTIFACT_CREATED,
                    AGENT_NAMES["orchestrator"],
                    {
                        "artifact": "spec",
                        "title": "Project specification",
                        "goals": spec.goals,
                        "acceptance_criteria": spec.acceptance_criteria,
                    },
                ),
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": "Maya prepared the specification. The team is waiting for approval."
                        if state.get("approval_required")
                        else "Maya prepared the specification. Arjun is starting the design.",
                        "stage": "1 of 8",
                        "status": "in_progress",
                        "risks": [],
                    },
                ),
            ],
        }

    def approval_gate(state: OfficeState) -> dict[str, Any]:
        if not state.get("approval_required"):
            return {}
        approved = interrupt(
            {
                "type": "spec_approval_required",
                "run_id": state["run_id"],
                "spec": state["spec"],
            }
        )
        return {"spec_approved": bool(approved), "approval_declined": not bool(approved)}

    def architect(state: OfficeState) -> dict[str, Any]:
        design = agent_runtime.structured(
            "architect",
            Design,
            Design(
                components=["Command-line interface", "CSV parser", "Schema validator", "JSON writer"],
                interfaces=["parse_args(argv)", "convert(input_path, output_path, schema_path)"],
                file_tree=["src/main.py", "src/converter.py", "tests/test_converter.py"],
                dependencies=["Python standard library"],
                data_flow=["Parse arguments", "Read CSV", "Validate rows", "Write JSON"],
            ),
            context={
                "spec": state["spec"],
                "previous_design": state.get("design"),
                "security_review": state.get("design_security_report"),
                "critic_review": state.get("design_critic_report"),
            },
            agent_configuration=state["agent_configuration"],
        )
        return {
            "design": design.model_dump(mode="json"),
            "review_phase": "design",
            "events": [
                emit(
                    state,
                    EventType.ARTIFACT_CREATED,
                    AGENT_NAMES["architect"],
                    {
                        "artifact": "design",
                        "title": "Technical design",
                        "components": design.components,
                        "dependencies": design.dependencies,
                        "file_tree": design.file_tree,
                        "data_flow": design.data_flow,
                    },
                ),
                emit(
                    state,
                    EventType.AGENT_STATUS,
                    AGENT_NAMES["architect"],
                    {"status": "working", "activity": "preparing design review"},
                ),
            ],
        }

    def cyber_security(state: OfficeState) -> dict[str, Any]:
        phase = state["review_phase"]
        report = agent_runtime.structured(
            "cyber_security",
            SecurityReport,
            SecurityReport(findings=[], gate="PASS"),
            context={
                "phase": phase,
                "spec": state["spec"],
                "design": state.get("design"),
                "implementation": state.get("implementation") if phase == "code" else None,
            },
            agent_configuration=state["agent_configuration"],
        )
        key = "design_security_report" if phase == "design" else "security_report"
        emitted = [
            emit(
                state,
                EventType.SECURITY_FINDING,
                AGENT_NAMES["cyber_security"],
                {
                    "phase": phase,
                    "gate": report.gate,
                    "finding": finding.model_dump(mode="json"),
                },
            )
            for finding in report.findings
        ]
        emitted.append(
            emit(
                state,
                EventType.MILESTONE_UPDATE,
                AGENT_NAMES["orchestrator"],
                {
                    "message": f"Sana's {phase} security gate is {report.gate}.",
                    "stage": "3 of 8" if phase == "design" else "6 of 8",
                    "status": report.gate.lower(),
                    "risks": [finding.title for finding in report.findings],
                },
            )
        )
        return {key: report.model_dump(mode="json"), "events": emitted}

    def critic(state: OfficeState) -> dict[str, Any]:
        phase = state["review_phase"]
        role = "critic_design" if phase == "design" else "critic_code"
        report = agent_runtime.structured(
            role,
            CriticReport,
            CriticReport(verdict="APPROVE", comments=[]),
            context={
                "phase": phase,
                "spec": state["spec"],
                "design": state.get("design"),
                "implementation": state.get("implementation") if phase == "code" else None,
                "security_report": (
                    state.get("design_security_report")
                    if phase == "design"
                    else state.get("security_report")
                ),
                "test_report": state.get("test_report") if phase == "code" else None,
            },
            agent_configuration=state["agent_configuration"],
        )
        key = "design_critic_report" if phase == "design" else "critic_report"
        return {
            key: report.model_dump(mode="json"),
            "events": [
                emit(
                    state,
                    EventType.REVIEW_VERDICT,
                    AGENT_NAMES["critic"],
                    {
                        "phase": phase,
                        "verdict": report.verdict,
                        "comments": [comment.model_dump(mode="json") for comment in report.comments],
                    },
                )
            ],
        }

    def design_review_gate(state: OfficeState) -> dict[str, Any]:
        approved = (
            SecurityReport.model_validate(state["design_security_report"]).gate == "PASS"
            and CriticReport.model_validate(state["design_critic_report"]).verdict == "APPROVE"
        )
        update: dict[str, Any] = {}
        if approved:
            return {
                "events": [
                    emit(
                        state,
                        EventType.MILESTONE_UPDATE,
                        AGENT_NAMES["orchestrator"],
                        {
                            "message": "Design review passed. Dev is starting implementation.",
                            "stage": "3 of 8",
                            "status": "in_progress",
                            "risks": [],
                        },
                    )
                ]
            }
        iteration = state.get("design_iterations", 0)
        if iteration < max_design_loops:
            update["design_iterations"] = iteration + 1
            update["events"] = [
                emit(
                    state,
                    EventType.LOOP_ITERATION,
                    AGENT_NAMES["orchestrator"],
                    {"loop": "design_review", "iteration": iteration + 1, "limit": max_design_loops},
                ),
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": "Design review found blockers. Arjun will revise the design.",
                        "stage": "3 of 8",
                        "status": "in_progress",
                        "risks": ["Design or threat-model review requested changes."],
                    },
                ),
            ]
        else:
            update["escalation_reason"] = "Design review remained blocked after the allowed revisions."
            update["events"] = [
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": "Design review is still blocked at the iteration limit. Maya is deciding whether to stop.",
                        "stage": "3 of 8",
                        "status": "blocked",
                        "risks": [update["escalation_reason"]],
                    },
                )
            ]
        return update

    def developer(state: OfficeState) -> dict[str, Any]:
        prior_data = state.get("implementation")
        prior = Implementation.model_validate(prior_data) if prior_data else None
        default_files = (
            prior.files
            if prior is not None
            else {
                "src/main.py": (
                    '"""CSV to JSON command-line entry point."""\n'
                    "def main() -> int:\n"
                    "    raise NotImplementedError('Replace with the designed implementation')\n"
                ),
                "tests/test_converter.py": '"""Acceptance tests for CSV conversion."""\n',
            }
        )
        implementation = agent_runtime.structured(
            "developer",
            Implementation,
            Implementation(
                files=default_files,
                summary="Mock implementation artifacts ready for review.",
            ),
            context={
                "spec": state["spec"],
                "design": state["design"],
                "previous_implementation": prior_data,
                "security_report": state.get("security_report"),
                "critic_report": state.get("critic_report"),
                "test_report": state.get("test_report"),
            },
            agent_configuration=state["agent_configuration"],
        )
        return {
            "implementation": implementation.model_dump(mode="json"),
            "review_phase": "code",
            "events": [
                emit(
                    state,
                    EventType.AGENT_STATUS,
                    AGENT_NAMES["developer"],
                    {"status": "working", "activity": "implementing the approved design"},
                ),
                emit(
                    state,
                    EventType.ARTIFACT_CREATED,
                    AGENT_NAMES["developer"],
                    {
                        "artifact": "code",
                        "files": sorted(implementation.files),
                        "summary": implementation.summary,
                    },
                ),
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": "Dev prepared the implementation artifacts. Tara, Sana, and Ojas are reviewing them.",
                        "stage": "4 of 8",
                        "status": "in_progress",
                        "risks": [],
                    },
                ),
            ],
        }

    def tester(state: OfficeState) -> dict[str, Any]:
        report = agent_runtime.structured(
            "tester",
            TestReport,
            TestReport(passed=2, failed=0, failing_cases=[], repro_steps=[]),
            context={
                "spec": state["spec"],
                "design": state["design"],
                "implementation": state["implementation"],
            },
            agent_configuration=state["agent_configuration"],
        )
        return {
            "test_report": report.model_dump(mode="json"),
            "events": [
                emit(
                    state,
                    EventType.TEST_RESULT,
                    AGENT_NAMES["tester"],
                    report.model_dump(mode="json"),
                ),
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": f"Tara's test report has {report.passed} passing and {report.failed} failing cases.",
                        "stage": "5 of 8",
                        "status": "passed" if report.failed == 0 else "failed",
                        "risks": report.failing_cases,
                    },
                ),
            ],
        }

    def documentation(state: OfficeState) -> dict[str, Any]:
        report = agent_runtime.structured(
            "documentation",
            DocumentationReport,
            DocumentationReport(
                files={
                    "README.md": (
                        "# Generated tool\n\n"
                        f"Implements: {state['prompt']}\n\n"
                        "This is a mock workflow artifact; replace it with final verified usage."
                    )
                },
                summary="Mock usage documentation prepared.",
            ),
            context={
                "spec": state["spec"],
                "implementation": state["implementation"],
                "test_report": state.get("test_report"),
            },
            agent_configuration=state["agent_configuration"],
        )
        return {
            "documentation": report.model_dump(mode="json"),
            "events": [
                emit(
                    state,
                    EventType.ARTIFACT_CREATED,
                    AGENT_NAMES["documentation"],
                    {
                        "artifact": "documentation",
                        "files": sorted(report.files),
                        "summary": report.summary,
                    },
                ),
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": "Doc prepared the usage notes. Maya is checking the final gates.",
                        "stage": "7 of 8",
                        "status": "in_progress",
                        "risks": [],
                    },
                ),
            ],
        }

    def orchestrator_final(state: OfficeState) -> dict[str, Any]:
        issues: list[str] = []
        design_security_data = state.get("design_security_report")
        design_critic_data = state.get("design_critic_report")
        security_data = state.get("security_report")
        critic_data = state.get("critic_report")
        test_data = state.get("test_report")
        design_security = SecurityReport.model_validate(design_security_data) if design_security_data else None
        design_critic = CriticReport.model_validate(design_critic_data) if design_critic_data else None
        security = SecurityReport.model_validate(security_data) if security_data else None
        critic_report = CriticReport.model_validate(critic_data) if critic_data else None
        test_report = TestReport.model_validate(test_data) if test_data else None
        if state.get("approval_declined"):
            issues.append("The user declined specification approval.")
        if state.get("escalation_reason"):
            issues.append(state["escalation_reason"])
        if design_security and design_security.gate != "PASS":
            issues.append("The design security gate failed.")
        if design_critic and design_critic.verdict != "APPROVE":
            issues.append("The design critic review did not approve the design.")
        if security and security.gate != "PASS":
            issues.append("The code security gate failed.")
        if critic_report and critic_report.verdict != "APPROVE":
            issues.append("The code critic review requested changes.")
        if test_report and test_report.failed:
            issues.append(f"{test_report.failed} test case(s) failed.")
        approved = not issues and bool(state.get("documentation"))
        final = FinalAcceptance(
            accepted=approved,
            status="completed" if approved else "failed",
            known_issues=issues,
            summary=(
                "The run passed its configured mock acceptance gates."
                if approved
                else "The run stopped without delivery because one or more gates remain blocked."
            ),
        )
        return {
            "final_acceptance": final.model_dump(mode="json"),
            "events": [
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": final.summary,
                        "stage": "8 of 8",
                        "status": final.status,
                        "risks": final.known_issues,
                    },
                ),
                emit(
                    state,
                    EventType.RUN_COMPLETE,
                    AGENT_NAMES["orchestrator"],
                    final.model_dump(mode="json"),
                ),
            ],
        }

    def after_approval(state: OfficeState) -> Literal["architect", "orchestrator_final"]:
        return "architect" if state.get("spec_approved") else "orchestrator_final"

    def after_design_review(state: OfficeState) -> Literal["developer", "architect", "orchestrator_final"]:
        if (
            SecurityReport.model_validate(state["design_security_report"]).gate == "PASS"
            and CriticReport.model_validate(state["design_critic_report"]).verdict == "APPROVE"
        ):
            return "developer"
        if state.get("escalation_reason"):
            return "orchestrator_final"
        return "architect"

    def after_code_review(state: OfficeState) -> Literal["documentation", "developer", "orchestrator_final"]:
        gates_pass = (
            SecurityReport.model_validate(state["security_report"]).gate == "PASS"
            and CriticReport.model_validate(state["critic_report"]).verdict == "APPROVE"
            and TestReport.model_validate(state["test_report"]).failed == 0
        )
        if gates_pass:
            return "documentation"
        if state.get("escalation_reason"):
            return "orchestrator_final"
        return "developer"

    def code_review_gate(state: OfficeState) -> dict[str, Any]:
        gates_pass = (
            SecurityReport.model_validate(state["security_report"]).gate == "PASS"
            and CriticReport.model_validate(state["critic_report"]).verdict == "APPROVE"
            and TestReport.model_validate(state["test_report"]).failed == 0
        )
        if gates_pass:
            return {}
        iteration = state.get("fix_iterations", 0)
        if iteration < max_fix_iterations:
            next_iteration = iteration + 1
            return {
                "fix_iterations": next_iteration,
                "events": [
                    emit(
                        state,
                        EventType.LOOP_ITERATION,
                        AGENT_NAMES["orchestrator"],
                        {"loop": "code_review", "iteration": next_iteration, "limit": max_fix_iterations},
                    ),
                    emit(
                        state,
                        EventType.MILESTONE_UPDATE,
                        AGENT_NAMES["orchestrator"],
                        {
                            "message": "A code review gate found issues. Dev will make a bounded fix pass.",
                            "stage": "6 of 8",
                            "status": "in_progress",
                            "risks": _gate_issues(state),
                        },
                    ),
                ],
            }
        reason = "Code review gates remained blocked after the allowed fix iterations."
        return {
            "escalation_reason": reason,
            "events": [
                emit(
                    state,
                    EventType.MILESTONE_UPDATE,
                    AGENT_NAMES["orchestrator"],
                    {
                        "message": "Code review is still blocked at the iteration limit. Maya is deciding whether to stop.",
                        "stage": "6 of 8",
                        "status": "blocked",
                        "risks": _gate_issues(state),
                    },
                )
            ],
        }

    def _gate_issues(state: OfficeState) -> list[str]:
        issues: list[str] = []
        if SecurityReport.model_validate(state["security_report"]).gate != "PASS":
            issues.append("Security gate failed.")
        critic_report = CriticReport.model_validate(state["critic_report"])
        if critic_report.verdict != "APPROVE":
            issues.extend(comment.comment for comment in critic_report.comments)
        test_report = TestReport.model_validate(state["test_report"])
        if test_report.failed:
            issues.extend(test_report.failing_cases)
        return issues

    builder = StateGraph(OfficeState)
    builder.add_node("orchestrator_spec", orchestrator_spec)
    builder.add_node("approval_gate", approval_gate)
    builder.add_node("architect", architect)
    builder.add_node("cyber_security", cyber_security)
    builder.add_node("critic", critic)
    builder.add_node("design_review_gate", design_review_gate)
    builder.add_node("developer", developer)
    builder.add_node("tester", tester)
    builder.add_node("code_review_join", lambda _: {})
    builder.add_node("code_review_gate", code_review_gate)
    builder.add_node("documentation", documentation)
    builder.add_node("orchestrator_final", orchestrator_final)

    builder.add_edge(START, "orchestrator_spec")
    builder.add_edge("orchestrator_spec", "approval_gate")
    builder.add_conditional_edges(
        "approval_gate",
        after_approval,
        {"architect": "architect", "orchestrator_final": "orchestrator_final"},
    )
    builder.add_edge("architect", "cyber_security")
    builder.add_edge("cyber_security", "critic")
    builder.add_conditional_edges(
        "critic",
        lambda state: "design_review_gate" if state["review_phase"] == "design" else "code_review_gate",
        {"design_review_gate": "design_review_gate", "code_review_gate": "code_review_join"},
    )
    builder.add_conditional_edges(
        "design_review_gate",
        after_design_review,
        {
            "developer": "developer",
            "architect": "architect",
            "orchestrator_final": "orchestrator_final",
        },
    )
    builder.add_conditional_edges(
        "developer",
        lambda _: ["tester", "cyber_security", "critic"],
        ["tester", "cyber_security", "critic"],
    )
    builder.add_edge(["tester", "cyber_security", "critic"], "code_review_join")
    builder.add_edge("code_review_join", "code_review_gate")
    builder.add_conditional_edges(
        "code_review_gate",
        after_code_review,
        {
            "documentation": "documentation",
            "developer": "developer",
            "orchestrator_final": "orchestrator_final",
        },
    )
    builder.add_edge("documentation", "orchestrator_final")
    builder.add_edge("orchestrator_final", END)
    return builder.compile(checkpointer=checkpointer)
