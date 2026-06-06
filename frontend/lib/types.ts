// Enums
export type Severity = "P1" | "P2" | "P3" | "P4"
export type IncidentStatus = "investigating" | "consensus" | "awaiting_approval" | "resolved" | "failed"
export type AgentName = "commander" | "log_forensics" | "telemetry_intel" | "deployment_intel" | "consensus_engine" | "postmortem_intel" | "safety_validator"
export type AgentStatus = "idle" | "investigating" | "challenging" | "done" | "error"
export type ChallengeVerdict = "AGREE" | "DISAGREE"
export type ApprovalStatus = "pending" | "approved" | "rejected"
export type RiskLevel = "low" | "medium" | "high" | "critical"

// Core Models
export interface Incident {
  id: string
  title: string
  description: string
  severity: Severity
  source: string
  metadata: Record<string, any>
  status: IncidentStatus
  created_at: string
  updated_at: string
  agent_statuses: Record<AgentName, AgentStatus>
  investigation_round: number
  consensus_confidence: number | null
}

export interface IncidentSummary {
  id: string
  title: string
  severity: Severity
  status: IncidentStatus
  created_at: string
  consensus_confidence: number | null
}

export interface EvidenceNode {
  id: string
  incident_id: string
  agent: AgentName
  evidence_type: string
  summary: string
  raw_data: Record<string, any>
  confidence: number
  parent_ids: string[]
  timestamp: string
  round_number: number
}

export interface AgentFinding {
  id: string
  incident_id: string
  agent: AgentName
  summary: string
  root_cause_hypothesis: string
  supporting_evidence: string[]
  confidence: number
  round_number: number
  timestamp: string
}

export interface ChallengeResult {
  id: string
  incident_id: string
  challenger: AgentName
  target_finding_id: string
  verdict: ChallengeVerdict
  reasoning: string
  revised_confidence: number
  timestamp: string
}

export interface Conflict {
  id: string
  agent_a: AgentName
  agent_b: AgentName
  position_a: string
  position_b: string
  evidence_ids: string[]
  resolved: boolean
}

export interface Hypothesis {
  id: string
  incident_id: string
  title: string
  description: string
  confidence: number
  supporting_finding_ids: string[]
  round_number: number
  timestamp: string
}

export interface ConsensusResult {
  incident_id: string
  hypothesis: Hypothesis
  confidence: number
  conflicts: Conflict[]
  round_number: number
  evidence_chain: string[]
  timestamp: string
}

export interface ProposedAction {
  id: string
  incident_id: string
  title: string
  description: string
  risk_level: RiskLevel
  estimated_impact: string
  rollback_plan: string
  requires_approval: boolean
}

export interface ApprovalRequest {
  id: string
  incident_id: string
  action: ProposedAction
  similar_past_incidents: any[]
  requested_at: string
  decided_at: string | null
  decision: ApprovalStatus
  note: string | null
}

export interface TimelineEntry {
  timestamp: string
  event: string
  agent: AgentName | null
  round_number: number | null
}

export interface RemediationAction {
  action: string
  priority: string
  owner: string
  estimated_effort: string
}

export interface Postmortem {
  incident_id: string
  executive_summary: string
  timeline: TimelineEntry[]
  root_cause: string
  contributing_factors: string[]
  remediation_actions: RemediationAction[]
  prevention_recommendations: string[]
  recurrence_risk: number
  generated_at: string
}

export interface PastIncident {
  id: string
  title: string
  root_cause: string
  resolution: string
  similarity: number
  occurred_at: string
}

export interface RecurrenceReport {
  is_recurring: boolean
  occurrences_30d: number
  occurrences_90d: number
  similar_incidents: PastIncident[]
  pattern_description: string | null
}

export interface AgentStatusEntry {
  name: AgentName
  status: AgentStatus
}

export interface SwarmStatus {
  round: number
  agents: AgentStatusEntry[]
  consensus_confidence: number | null
}

export interface IncidentCreate {
  title: string
  description: string
  severity: Severity
  source: string
  metadata?: Record<string, any>
}

export interface IncidentCreateResponse {
  id: string
  status: IncidentStatus
  swarm: SwarmStatus
  similar_past_incidents: PastIncident[]
}

export interface ApprovalDecision {
  approved: boolean
  note?: string | null
}

// WebSocket events
export type SwarmEvent =
  | { event: "incident_created"; incident_id: string; timestamp: string; round: number; payload: { incident_id: string; title: string; severity: string } }
  | { event: "memory_recalled"; incident_id: string; timestamp: string; round: number; payload: { similar_count: number } }
  | { event: "swarm_dispatched"; incident_id: string; timestamp: string; round: number; payload: { agents: AgentName[]; round: number } }
  | { event: "agent_status_change"; incident_id: string; timestamp: string; round: number; payload: { agent_id: AgentName; status: AgentStatus } }
  | { event: "evidence_added"; incident_id: string; timestamp: string; round: number; payload: EvidenceNode }
  | { event: "finding_added"; incident_id: string; timestamp: string; round: number; payload: AgentFinding }
  | { event: "conflict_detected"; incident_id: string; timestamp: string; round: number; payload: Conflict }
  | { event: "challenge_started"; incident_id: string; timestamp: string; round: number; payload: { agent_a: AgentName; agent_b: AgentName } }
  | { event: "challenge_resolved"; incident_id: string; timestamp: string; round: number; payload: ChallengeResult }
  | { event: "confidence_update"; incident_id: string; timestamp: string; round: number; payload: { round: number; confidence: number; trend: string } }
  | { event: "consensus_reached"; incident_id: string; timestamp: string; round: number; payload: ConsensusResult }
  | { event: "reinvestigation_needed"; incident_id: string; timestamp: string; round: number; payload: { reason: string; target_agents: AgentName[]; round: number } }
  | { event: "approval_requested"; incident_id: string; timestamp: string; round: number; payload: ApprovalRequest }
  | { event: "approval_response"; incident_id: string; timestamp: string; round: number; payload: { approval_id: string; incident_id: string; decision: string; note: string | null } }
  | { event: "incident_resolved"; incident_id: string; timestamp: string; round: number; payload: { incident_id: string; status: string } }
  | { event: "postmortem_ready"; incident_id: string; timestamp: string; round: number; payload: { incident_id: string; recurrence_risk: number; remediation_count: number } }
  | { event: "timeline_updated"; incident_id: string; timestamp: string; round: number; payload: TimelineEntry }
  | { event: "error"; incident_id: string; timestamp: string; round: number; payload: { code: string; message: string; agent: AgentName | null } }
  | { event: "incident_state_sync"; incident_id: string; timestamp: string; round: number; payload: { timeline: TimelineEntry[]; agent_findings: AgentFinding[]; evidence_nodes: EvidenceNode[] } }
  | { event: "connected"; incident_id: string; timestamp: string; round: number; payload: Record<string, never> }
  | { event: "ping"; incident_id: string; timestamp: string; round: number; payload: Record<string, never> }

// Incident UI state
export interface IncidentUIState {
  incident: Incident | null
  agentStatuses: Record<AgentName, AgentStatus>
  evidenceNodes: EvidenceNode[]
  findings: AgentFinding[]
  conflicts: Conflict[]
  consensus: ConsensusResult | null
  pendingApprovals: ApprovalRequest[]
  postmortem: Postmortem | null
  events: SwarmEvent[]
  connectionStatus: "connecting" | "connected" | "disconnected" | "error"
  similarPastIncidents: PastIncident[]
  timeline: TimelineEntry[]
}
