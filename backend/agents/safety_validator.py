import uuid
from datetime import datetime, timezone
from typing import List

import structlog

from app.models import (
    AgentName,
    ApprovalRequest,
    ApprovalStatus,
    ConsensusResult,
    Incident,
    ProposedAction,
    RiskAssessmentLLM,
    RiskLevel,
    SafetyValidationResult,
    Severity,
)
from services.event_bus import get_event_bus
from services.llm import AzureOpenAIClient

logger = structlog.get_logger(__name__)


class SafetyValidator:
    """
    Risk-scores proposed actions and gates destructive operations.
    Uses LLM for risk assessment + rule-based overrides for critical actions.
    """

    CRITICAL_PATTERNS = [
        "delete", "drop", "truncate", "destroy", "terminate all",
        "production database", "prod db", "force restart all",
    ]

    def __init__(self, llm: AzureOpenAIClient):
        self.llm = llm
        self.event_bus = get_event_bus()

    async def validate(
        self, consensus: ConsensusResult, incident: Incident
    ) -> SafetyValidationResult:
        """
        1. Extract proposed actions from consensus hypothesis (LLM call)
        2. For each action: compute risk_level (LLM + rule overrides)
        3. Actions with risk_level in {high, critical} → requires_approval = True
        4. Actions matching CRITICAL_PATTERNS → always requires_approval = True
        5. Emit approval_required for each action needing approval
        6. Return SafetyValidationResult
        """
        # Step 1 — extract proposed actions from the consensus
        proposed_actions = await self._extract_actions(consensus, incident)

        approval_requests: List[ApprovalRequest] = []
        auto_approved: List[ProposedAction] = []

        for action in proposed_actions:
            # Step 2 — assess risk via LLM
            risk_assessment = await self._assess_risk(action.description, incident)

            # Update action with LLM risk assessment
            action = action.model_copy(
                update={
                    "risk_level": risk_assessment.risk_level,
                    "estimated_impact": risk_assessment.estimated_impact,
                    "rollback_plan": risk_assessment.rollback_plan,
                }
            )

            # Step 3 & 4 — apply rule overrides
            overridden_risk = await self.check_rule_overrides(action, incident)
            action = action.model_copy(update={"risk_level": overridden_risk})

            needs_approval = overridden_risk in (RiskLevel.high, RiskLevel.critical)
            action = action.model_copy(update={"requires_approval": needs_approval})

            if needs_approval:
                req = ApprovalRequest(
                    id=str(uuid.uuid4()),
                    incident_id=incident.id,
                    action=action,
                    similar_past_incidents=[],
                    requested_at=datetime.now(timezone.utc),
                    decision=ApprovalStatus.pending,
                )
                approval_requests.append(req)

                # Event emission moved to manager.py to prevent race condition
                logger.info(
                    "safety.approval_required",
                    incident_id=incident.id,
                    action=action.title,
                    risk_level=overridden_risk.value,
                )
            else:
                auto_approved.append(action)
                logger.info(
                    "safety.auto_approved",
                    incident_id=incident.id,
                    action=action.title,
                    risk_level=overridden_risk.value,
                )

        result = SafetyValidationResult(
            incident_id=incident.id,
            proposed_actions=proposed_actions,
            approval_requests=approval_requests,
            auto_approved_actions=auto_approved,
            validated_at=datetime.now(timezone.utc),
        )

        return result

    async def _extract_actions(
        self, consensus: ConsensusResult, incident: Incident
    ) -> List[ProposedAction]:
        """Use LLM to extract concrete remediation actions from the consensus hypothesis."""
        from pydantic import BaseModel as _BM

        class _ActionItem(_BM):
            title: str
            description: str

        class _ActionsLLM(_BM):
            actions: list[_ActionItem]

        try:
            result: _ActionsLLM = await self.llm.complete(
                system_prompt=(
                    "You are a safety validator. Given an incident consensus hypothesis, "
                    "extract concrete remediation actions. For each action provide a title "
                    "and description."
                ),
                user_message=(
                    f"Incident: {incident.title} (severity: {incident.severity.value})\n"
                    f"Consensus hypothesis: {consensus.hypothesis.title}\n"
                    f"Description: {consensus.hypothesis.description}\n"
                    f"Confidence: {consensus.confidence}\n\n"
                    f"List the concrete remediation actions needed."
                ),
                response_schema=_ActionsLLM,
                incident_id=incident.id,
            )

            actions = []
            for a in result.actions:
                actions.append(
                    ProposedAction(
                        id=str(uuid.uuid4()),
                        incident_id=incident.id,
                        title=a.title,
                        description=a.description,
                        risk_level=RiskLevel.medium,
                        estimated_impact="TBD",
                        rollback_plan="TBD",
                        requires_approval=False,
                    )
                )
            return actions

        except Exception as exc:
            logger.warning(
                "safety.extract_actions_fallback",
                incident_id=incident.id,
                error=str(exc),
            )
            # Fallback: a single generic action
            return [
                ProposedAction(
                    id=str(uuid.uuid4()),
                    incident_id=incident.id,
                    title="Investigate and remediate",
                    description=consensus.hypothesis.description,
                    risk_level=RiskLevel.medium,
                    estimated_impact="Unknown",
                    rollback_plan="Revert changes",
                    requires_approval=False,
                )
            ]

    async def _assess_risk(
        self, action_description: str, incident: Incident
    ) -> RiskAssessmentLLM:
        """
        LLM prompt: assess risk level, estimate impact, suggest rollback plan.
        """
        try:
            result: RiskAssessmentLLM = await self.llm.complete(
                system_prompt=(
                    "You are a safety risk assessor for SRE operations. "
                    "Assess the risk of a proposed remediation action. "
                    "Actions that modify production state, restart services, scale resources, "
                    "or change configurations MUST be rated as high or critical risk."
                ),
                user_message=(
                    f"Incident severity: {incident.severity.value}\n"
                    f"Proposed action: {action_description}\n\n"
                    f"Assess the risk level (low/medium/high/critical), "
                    f"estimate the impact, suggest a rollback plan, and justify your assessment."
                ),
                response_schema=RiskAssessmentLLM,
                incident_id=incident.id,
            )
            return result
        except Exception as exc:
            logger.warning(
                "safety.risk_assessment_fallback",
                incident_id=incident.id,
                error=str(exc),
            )
            return RiskAssessmentLLM(
                risk_level=RiskLevel.medium,
                estimated_impact="Unable to assess — defaulting to medium risk",
                rollback_plan="Revert changes and monitor",
                justification="LLM unavailable; using conservative default",
            )

    async def check_rule_overrides(self, action: ProposedAction, incident: Incident) -> RiskLevel:
        """
        Apply CRITICAL_PATTERNS matching.
        P1 incidents with high risk → escalate to critical.
        """
        desc_lower = action.description.lower()
        title_lower = action.title.lower()
        combined = f"{title_lower} {desc_lower}"

        # Check critical patterns
        for pattern in self.CRITICAL_PATTERNS:
            if pattern in combined:
                logger.info(
                    "safety.critical_pattern_match",
                    pattern=pattern,
                    action=action.title,
                )
                return RiskLevel.critical

        # P1 escalation: high → critical
        if incident.severity == Severity.P1 and action.risk_level == RiskLevel.high:
            logger.info(
                "safety.p1_escalation",
                action=action.title,
                incident_id=incident.id,
            )
            return RiskLevel.critical
            
        # P1 escalation: medium -> high (to ensure P1 incidents get human eyes on state changes)
        if incident.severity == Severity.P1 and action.risk_level == RiskLevel.medium:
            logger.info(
                "safety.p1_medium_to_high_escalation",
                action=action.title,
                incident_id=incident.id,
            )
            return RiskLevel.high

        return action.risk_level
