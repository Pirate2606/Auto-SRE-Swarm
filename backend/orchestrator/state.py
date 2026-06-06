from __future__ import annotations
import operator
from typing import Annotated, TypedDict

from app.models import (
    AgentFinding,
    ApprovalRequest,
    ApprovalStatus,
    ChallengeResult,
    Conflict,
    EvidenceNode,
    Hypothesis,
    IncidentStatus,
    PastIncident,
    Postmortem,
    ProposedAction,
    SafetyValidationResult,
    TimelineEntry,
)


class IncidentState(TypedDict):
    # Identity
    incident_id: str
    title: str
    description: str
    severity: str

    # Swarm state
    evidence_nodes: list[EvidenceNode]
    agent_findings: Annotated[list, operator.add]
    active_agents: list[str]
    challenge_results: list[ChallengeResult]

    # Consensus
    hypotheses: list[Hypothesis]
    consensus_confidence: float
    conflicts: list[Conflict]
    investigation_round: int  # max 3

    # Actions
    proposed_actions: list[ProposedAction]
    approval_status: ApprovalStatus
    approval_requests: list[ApprovalRequest]

    # Memory
    similar_past_incidents: list[PastIncident]

    # Lifecycle
    status: IncidentStatus
    postmortem: Postmortem | None
    messages: list
    timeline: list[TimelineEntry]
    safety_result: SafetyValidationResult | None
