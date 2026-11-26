from operator import add
from typing import Annotated, Any, TypedDict

class OfficeState(TypedDict, total=False):
    run_id: str
    prompt: str
    agent_configuration: dict[str, Any]
    approval_required: bool
    spec_approved: bool
    approval_declined: bool
    spec: dict[str, Any]
    design: dict[str, Any]
    design_security_report: dict[str, Any]
    design_critic_report: dict[str, Any]
    implementation: dict[str, Any]
    security_report: dict[str, Any]
    critic_report: dict[str, Any]
    test_report: dict[str, Any]
    documentation: dict[str, Any]
    final_acceptance: dict[str, Any]
    review_phase: str
    design_iterations: int
    fix_iterations: int
    escalation_reason: str
    events: Annotated[list[dict[str, Any]], add]
