import json
import uuid
from datetime import datetime, timezone
from typing import List

import structlog

from app.models import (
    AgentFinding,
    AgentName,
    ConsensusResult,
    EvidenceNode,
    PastIncident,
    Postmortem,
    PostmortemLLM,
    RemediationAction,
    TimelineEntry,
)
from agents.base import SwarmAgent, SwarmContext
from db.database import get_postmortems_container
from services.event_bus import get_event_bus
from services.llm import AzureOpenAIClient
from services.evidence_store import EvidenceStore
from services.event_bus import EventBus
from services.memory_store import IncidentMemoryStore

logger = structlog.get_logger(__name__)


class PostmortemIntelAgent(SwarmAgent):
    name = AgentName.postmortem_intel
    role_prompt = (
        "You are the Postmortem Intelligence Agent.\n"
        "You generate rigorous, blameless postmortems from incident investigation records.\n"
        "Your output follows industry standard (Google SRE postmortem format).\n"
        "You must: be specific (cite timestamps, metrics, agent findings). "
        "Never use vague language like \"something went wrong.\"\n"
        "Include actionable remediation items with clear owners and timelines."
    )

    def __init__(
        self,
        llm: AzureOpenAIClient,
        evidence_store: EvidenceStore,
        event_bus: EventBus,
        memory_store: IncidentMemoryStore | None = None,
    ):
        super().__init__(llm, evidence_store, event_bus)
        self.memory_store = memory_store or IncidentMemoryStore()

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    async def generate(
        self,
        ctx: SwarmContext,
        consensus: ConsensusResult,
        timeline: list[TimelineEntry],
    ) -> Postmortem:
        """
        1. Build a comprehensive prompt from: full evidence graph, all agent findings,
           consensus result, event timeline, similar past incidents
        2. Call LLM with Postmortem schema as structured output
        3. Enrich remediation_actions with proven fixes from MemoryStore
        4. Compute recurrence_risk from MemoryStore
        5. Store postmortem in DB
        6. Store incident in MemoryStore for future recall
        7. Emit postmortem_ready event
        8. Return Postmortem
        """
        # Gather evidence graph
        evidence_nodes = await self.evidence_store.get_incident_graph(ctx.incident_id)

        # Get proven remediations and recurrence report
        proven_remediations = await self.memory_store.get_proven_remediations(
            consensus.hypothesis.description
        )
        recurrence = await self.memory_store.detect_recurrence(
            ctx.incident_description, ctx.incident_id
        )

        # Step 4 (Moved up) — recurrence risk
        recurrence_risk = 0.0
        if recurrence.is_recurring:
            # Scale risk by occurrence count
            recurrence_risk = min(
                0.3 + (recurrence.occurrences_30d * 0.15) + (recurrence.occurrences_90d * 0.05),
                1.0,
            )

        # Step 1 — build prompt
        prompt = self._build_postmortem_prompt(
            ctx=ctx,
            consensus=consensus,
            timeline=timeline,
            evidence_nodes=evidence_nodes,
            proven_remediations=proven_remediations,
            recurrence_risk=recurrence_risk,
        )

        # Step 2 — LLM call
        try:
            llm_result: PostmortemLLM = await self.llm.complete(
                system_prompt=self.role_prompt,
                user_message=prompt,
                response_schema=PostmortemLLM,
                incident_id=ctx.incident_id,
                max_tokens=4000,
            )
        except Exception as exc:
            logger.error(
                "postmortem.llm_error",
                incident_id=ctx.incident_id,
                error=str(exc),
            )
            # Fallback postmortem
            llm_result = PostmortemLLM(
                executive_summary=f"Investigation of {ctx.incident_title} concluded with "
                    f"consensus confidence {consensus.confidence:.2f}.",
                root_cause=consensus.hypothesis.description,
                contributing_factors=["Unable to generate detailed factors — LLM unavailable"],
                remediation_actions=[{
                    "action": "Review consensus findings manually",
                    "priority": "immediate",
                    "owner": "SRE On-Call",
                    "estimated_effort": "2h",
                }],
                prevention_recommendations=["Review and implement automated safeguards"],
            )

        # Step 3 — enrich remediation actions with proven fixes
        remediation_actions = self._build_remediation_actions(
            llm_result.remediation_actions, proven_remediations
        )

        postmortem = Postmortem(
            incident_id=ctx.incident_id,
            executive_summary=llm_result.executive_summary,
            timeline=timeline,
            root_cause=llm_result.root_cause,
            contributing_factors=llm_result.contributing_factors,
            remediation_actions=remediation_actions,
            prevention_recommendations=llm_result.prevention_recommendations,
            recurrence_risk=round(recurrence_risk, 2),
            generated_at=datetime.now(timezone.utc),
        )

        # Step 5 — store in DB
        await self._persist_postmortem(postmortem)

        # Step 6 — store incident in memory for future recall
        try:
            await self.memory_store.store_incident(
                incident_id=ctx.incident_id,
                title=ctx.incident_title,
                root_cause=llm_result.root_cause,
                resolution=llm_result.executive_summary,
                metadata={
                    "severity": ctx.severity,
                    "confidence": consensus.confidence,
                    "round": consensus.round_number,
                },
            )
        except Exception as exc:
            logger.warning(
                "postmortem.memory_store_error",
                incident_id=ctx.incident_id,
                error=str(exc),
            )

        # Step 7 — emit event (include full postmortem for the frontend)
        await self.event_bus.publish(
            ctx.incident_id,
            {
                "type": "postmortem_ready",
                "payload": {
                    "incident_id": ctx.incident_id,
                    "executive_summary": postmortem.executive_summary,
                    "root_cause": postmortem.root_cause,
                    "contributing_factors": postmortem.contributing_factors,
                    "remediation_actions": [r.model_dump(mode="json") for r in postmortem.remediation_actions],
                    "prevention_recommendations": postmortem.prevention_recommendations,
                    "recurrence_risk": postmortem.recurrence_risk,
                    "timeline": [t.model_dump(mode="json") for t in postmortem.timeline],
                    "generated_at": postmortem.generated_at.isoformat(),
                    "remediation_count": len(remediation_actions),
                },
            },
        )

        logger.info(
            "postmortem.generated",
            incident_id=ctx.incident_id,
            recurrence_risk=recurrence_risk,
            remediation_count=len(remediation_actions),
        )

        return postmortem

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_postmortem_prompt(
        self,
        ctx: SwarmContext,
        consensus: ConsensusResult,
        timeline: list[TimelineEntry],
        evidence_nodes: list[EvidenceNode],
        proven_remediations: list[str],
        recurrence_risk: float,
    ) -> str:
        # Timeline
        timeline_block = "\n".join(
            f"- [{e.timestamp.isoformat()}] {e.event}"
            + (f" (agent: {e.agent.value})" if e.agent else "")
            for e in timeline
        ) if timeline else "(no timeline entries)"

        # Evidence chain — top 10
        evidence_block = "\n".join(
            f"- [{n.agent.value}/{n.evidence_type}] {n.summary} "
            f"(confidence={n.confidence:.2f}, round={n.round_number})"
            for n in evidence_nodes[:10]
        ) if evidence_nodes else "(no evidence)"

        # Agent findings
        findings_block = "\n".join(
            f"- [{f.agent.value}] {f.summary} "
            f"(hypothesis: {f.root_cause_hypothesis}, confidence={f.confidence:.2f})"
            for f in ctx.other_findings
        ) if ctx.other_findings else "(no findings)"

        # Past incidents
        past_block = "\n".join(
            f"- {p.title}: Root cause — {p.root_cause}. Resolution — {p.resolution} "
            f"(similarity={p.similarity:.2f})"
            for p in ctx.similar_past_incidents[:5]
        ) if ctx.similar_past_incidents else "(no similar past incidents)"

        # Proven remediations
        remediation_block = "\n".join(
            f"- {r}" for r in proven_remediations
        ) if proven_remediations else "(no proven remediations found)"

        # Consensus
        consensus_block = (
            f"Hypothesis: {consensus.hypothesis.title}\n"
            f"Description: {consensus.hypothesis.description}\n"
            f"Confidence: {consensus.confidence:.2f}\n"
            f"Round: {consensus.round_number}\n"
            f"Conflicts: {len(consensus.conflicts)}"
        )

        start_time = timeline[0].timestamp.isoformat() if timeline else "unknown"
        end_time = timeline[-1].timestamp.isoformat() if timeline else "unknown"

        return (
            f"INCIDENT CONTEXT:\n"
            f"- Title: {ctx.incident_title}\n"
            f"- Severity: {ctx.severity}\n"
            f"- Duration: {start_time} → {end_time}\n\n"
            f"INVESTIGATION RECORD:\n"
            f"{findings_block}\n\n"
            f"FINAL CONSENSUS:\n"
            f"{consensus_block}\n\n"
            f"EVIDENCE CHAIN:\n"
            f"{evidence_block}\n\n"
            f"EVENT TIMELINE:\n"
            f"{timeline_block}\n\n"
            f"SIMILAR PAST INCIDENTS:\n"
            f"{past_block}\n\n"
            f"PROVEN REMEDIATIONS FOR SIMILAR ROOT CAUSES:\n"
            f"{remediation_block}\n\n"
            f"Recurrence risk score: {recurrence_risk:.2f}\n\n"
            f"Generate a complete postmortem following Google SRE format. "
            f"Be specific — cite timestamps, metrics, and agent findings. "
            f"Include actionable remediation items with clear owners and timelines."
        )

    # ------------------------------------------------------------------
    # Remediation enrichment
    # ------------------------------------------------------------------

    def _build_remediation_actions(
        self,
        llm_actions: list[RemediationAction],
        proven_remediations: list[str],
    ) -> list[RemediationAction]:
        actions: list[RemediationAction] = []
        seen_actions: set[str] = set()

        # From LLM output
        for a in llm_actions:
            action_text = getattr(a, "action", "")
            if action_text and action_text not in seen_actions:
                seen_actions.add(action_text)
                actions.append(
                    RemediationAction(
                        action=action_text,
                        priority=getattr(a, "priority", "short_term"),
                        owner=getattr(a, "owner", "SRE Team"),
                        estimated_effort=getattr(a, "estimated_effort", "TBD"),
                    )
                )

        # Enrich with proven remediations from memory store
        for rem in proven_remediations:
            if rem not in seen_actions:
                seen_actions.add(rem)
                actions.append(
                    RemediationAction(
                        action=f"[PROVEN FIX] {rem}",
                        priority="immediate",
                        owner="SRE Team",
                        estimated_effort="Varies",
                    )
                )

        return actions

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_postmortem(self, postmortem: Postmortem):
        try:
            container = await get_postmortems_container()
            doc = {
                "id": postmortem.incident_id,
                "incident_id": postmortem.incident_id,
                "executive_summary": postmortem.executive_summary,
                "timeline": [t.model_dump(mode="json") for t in postmortem.timeline],
                "root_cause": postmortem.root_cause,
                "contributing_factors": postmortem.contributing_factors,
                "remediation_actions": [r.model_dump(mode="json") for r in postmortem.remediation_actions],
                "prevention_recommendations": postmortem.prevention_recommendations,
                "recurrence_risk": postmortem.recurrence_risk,
                "generated_at": postmortem.generated_at.isoformat(),
            }
            await container.upsert_item(doc)
            logger.info("postmortem.persisted", incident_id=postmortem.incident_id)
        except Exception as exc:
            logger.error(
                "postmortem.persist_error",
                incident_id=postmortem.incident_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Abstract method stubs (not used for postmortem generation flow)
    # ------------------------------------------------------------------

    async def _fetch_domain_data(self, ctx: SwarmContext) -> dict:
        return {}

    def _get_investigation_prompt(self, ctx: SwarmContext, domain_data: dict) -> str:
        return ""
