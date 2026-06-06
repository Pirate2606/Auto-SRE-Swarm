from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict

class Severity(str, Enum):
    P1="P1"
    P2="P2"
    P3="P3"
    P4="P4"

class IncidentStatus(str, Enum):
    investigating="investigating"
    consensus="consensus"
    awaiting_approval="awaiting_approval"
    resolved="resolved"
    failed="failed"

class AgentName(str, Enum):
    commander="commander"
    log_forensics="log_forensics"
    telemetry_intel="telemetry_intel"
    deployment_intel="deployment_intel"
    consensus_engine="consensus_engine"
    postmortem_intel="postmortem_intel"
    safety_validator="safety_validator"

class AgentStatus(str, Enum):
    idle="idle"
    investigating="investigating"
    challenging="challenging"
    done="done"
    error="error"

class ChallengeVerdict(str, Enum):
    agree="AGREE"
    disagree="DISAGREE"

class ApprovalStatus(str, Enum):
    pending="pending"
    approved="approved"
    rejected="rejected"

class RiskLevel(str, Enum):
    low="low"
    medium="medium"
    high="high"
    critical="critical"

class EvidenceNode(BaseModel):
    id: str
    incident_id: str
    agent: AgentName
    evidence_type: str
    summary: str
    raw_data: dict
    confidence: float = Field(ge=0.0, le=1.0)
    parent_ids: list[str] = []
    timestamp: datetime
    round_number: int

class AgentFinding(BaseModel):
    id: str
    incident_id: str
    agent: AgentName
    summary: str
    root_cause_hypothesis: str
    supporting_evidence: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    round_number: int
    timestamp: datetime

class ChallengeResult(BaseModel):
    id: str
    incident_id: str
    challenger: AgentName
    target_finding_id: str
    verdict: ChallengeVerdict
    reasoning: str
    revised_confidence: float
    timestamp: datetime

class Conflict(BaseModel):
    id: str
    agent_a: AgentName
    agent_b: AgentName
    position_a: str
    position_b: str
    evidence_ids: list[str]
    resolved: bool = False

class Hypothesis(BaseModel):
    id: str
    incident_id: str
    title: str
    description: str
    confidence: float
    supporting_finding_ids: list[str]
    round_number: int
    timestamp: datetime

class ConsensusResult(BaseModel):
    incident_id: str
    hypothesis: Hypothesis
    confidence: float
    conflicts: list[Conflict]
    round_number: int
    evidence_chain: list[str]
    timestamp: datetime

class ProposedAction(BaseModel):
    id: str
    incident_id: str
    title: str
    description: str
    risk_level: RiskLevel
    estimated_impact: str
    rollback_plan: str
    requires_approval: bool

class ApprovalRequest(BaseModel):
    id: str
    incident_id: str
    action: ProposedAction
    similar_past_incidents: list[dict]
    requested_at: datetime
    decided_at: datetime | None = None
    decision: ApprovalStatus = ApprovalStatus.pending
    note: str | None = None

class ApprovalDecision(BaseModel):
    approved: bool
    note: str | None = None

class TimelineEntry(BaseModel):
    timestamp: datetime
    event: str
    agent: AgentName | None = None
    round_number: int | None = None

class RemediationAction(BaseModel):
    action: str
    priority: str
    owner: str
    estimated_effort: str

class Postmortem(BaseModel):
    incident_id: str
    executive_summary: str
    timeline: list[TimelineEntry]
    root_cause: str
    contributing_factors: list[str]
    remediation_actions: list[RemediationAction]
    prevention_recommendations: list[str]
    recurrence_risk: float = Field(ge=0.0, le=1.0)
    generated_at: datetime

class IncidentCreate(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    description: str = Field(min_length=10)
    severity: Severity
    source: str
    metadata: dict = {}

class Incident(BaseModel):
    id: str
    title: str
    description: str
    severity: Severity
    source: str
    metadata: dict
    status: IncidentStatus
    created_at: datetime
    updated_at: datetime
    agent_statuses: dict[AgentName, AgentStatus] = {}
    investigation_round: int = 0
    consensus_confidence: float | None = None

class IncidentSummary(BaseModel):
    id: str
    title: str
    severity: Severity
    status: IncidentStatus
    created_at: datetime
    consensus_confidence: float | None = None

class PastIncident(BaseModel):
    id: str
    title: str
    root_cause: str
    resolution: str
    similarity: float
    occurred_at: datetime

class RecurrenceReport(BaseModel):
    is_recurring: bool
    occurrences_30d: int
    occurrences_90d: int
    similar_incidents: list[PastIncident]
    pattern_description: str | None = None

class AgentStatusEntry(BaseModel):
    name: AgentName
    status: AgentStatus

class SwarmStatus(BaseModel):
    round: int
    agents: list[AgentStatusEntry]
    consensus_confidence: float | None = None

class IncidentCreateResponse(BaseModel):
    id: str
    status: IncidentStatus
    swarm: SwarmStatus
    similar_past_incidents: list[PastIncident]

# LLM Response Schemas
class AgentFindingLLM(BaseModel):
    root_cause_hypothesis: str
    summary: str
    supporting_evidence: list[str]  # human-readable evidence points
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_type: str

class ChallengeResultLLM(BaseModel):
    verdict: ChallengeVerdict
    reasoning: str
    confidence_adjustment: float = Field(ge=-0.5, le=0.5)

class RiskAssessmentLLM(BaseModel):
    risk_level: RiskLevel
    estimated_impact: str
    rollback_plan: str
    justification: str

class PostmortemLLM(BaseModel):
    executive_summary: str
    root_cause: str
    contributing_factors: list[str]
    remediation_actions: list[RemediationAction]
    prevention_recommendations: list[str]

class SafetyValidationResult(BaseModel):
    incident_id: str
    proposed_actions: list[ProposedAction]
    approval_requests: list[ApprovalRequest]
    auto_approved_actions: list[ProposedAction]
    validated_at: datetime

# Websocket Swarm Events
from typing import Literal, Union

class AgentStatusChangePayload(BaseModel):
    agent_id: str
    status: AgentStatus

class EventAgentStatusChange(BaseModel):
    type: Literal["agent_status_change"]
    payload: AgentStatusChangePayload

class EventFindingAdded(BaseModel):
    type: Literal["finding_added"]
    payload: AgentFinding

class EventEvidenceAdded(BaseModel):
    type: Literal["evidence_added"]
    payload: EvidenceNode

class EventHypothesisProposed(BaseModel):
    type: Literal["hypothesis_proposed"]
    payload: Hypothesis

class EventConflictDetected(BaseModel):
    type: Literal["conflict_detected"]
    payload: Conflict

class EventChallengeResolved(BaseModel):
    type: Literal["challenge_resolved"]
    payload: ChallengeResult

class EventActionProposed(BaseModel):
    type: Literal["action_proposed"]
    payload: ProposedAction

class EventApprovalRequested(BaseModel):
    type: Literal["approval_requested"]
    payload: ApprovalRequest

class EventConsensusReached(BaseModel):
    type: Literal["consensus_reached"]
    payload: ConsensusResult

SwarmEvent = Union[
    EventAgentStatusChange,
    EventFindingAdded,
    EventEvidenceAdded,
    EventHypothesisProposed,
    EventConflictDetected,
    EventChallengeResolved,
    EventActionProposed,
    EventApprovalRequested,
    EventConsensusReached
]

