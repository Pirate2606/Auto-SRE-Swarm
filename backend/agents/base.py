import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

import structlog

from app.models import (
    AgentFinding,
    AgentFindingLLM,
    AgentName,
    AgentStatus,
    ChallengeResult,
    ChallengeResultLLM,
    ChallengeVerdict,
    EvidenceNode,
    PastIncident,
)
from services.evidence_store import EvidenceStore
from services.event_bus import EventBus
from services.llm import AzureOpenAIClient
from services.mock_cloud import MockCloudService

import autogen
from app.config import get_settings

logger = structlog.get_logger(__name__)


@dataclass
class SwarmContext:
    incident_id: str
    incident_title: str
    incident_description: str
    severity: str
    investigation_round: int
    existing_evidence: List[EvidenceNode] = field(default_factory=list)
    other_findings: List[AgentFinding] = field(default_factory=list)
    similar_past_incidents: List[PastIncident] = field(default_factory=list)
    mock_cloud: MockCloudService = field(default_factory=MockCloudService)


class SwarmAgent(autogen.ConversableAgent, ABC):
    name: AgentName
    role_prompt: str  # system prompt — agent persona, constraints, output format

    def __init__(
        self,
        llm: AzureOpenAIClient,
        evidence_store: EvidenceStore,
        event_bus: EventBus,
    ):
        settings = get_settings()

        config = {
            "model": settings.AZURE_OPENAI_DEPLOYMENT,
            "api_key": settings.AZURE_OPENAI_API_KEY,
        }
        if "/v1" in settings.AZURE_OPENAI_ENDPOINT:
            config["base_url"] = settings.AZURE_OPENAI_ENDPOINT
        else:
            config["base_url"] = settings.AZURE_OPENAI_ENDPOINT
            config["api_type"] = "azure"
            config["api_version"] = settings.AZURE_OPENAI_API_VERSION

        llm_config = {
            "config_list": [config],
            "temperature": 0.2,
            "cache_seed": None,
        }

        super().__init__(
            name=self.name.value,
            system_message=self.role_prompt,
            llm_config=llm_config,
            human_input_mode="NEVER",
        )
        self.llm = llm
        self.evidence_store = evidence_store
        self.event_bus = event_bus
        self._current_incident_id = None

    # ------------------------------------------------------------------
    # Public contract
    # ------------------------------------------------------------------

    async def investigate(self, ctx: SwarmContext) -> AgentFinding:
        self._current_incident_id = ctx.incident_id
        await self._emit_status(ctx.incident_id, AgentStatus.investigating)

        try:
            # Step 2 — domain data
            domain_data = await self._fetch_domain_data(ctx)

            # Step 3 — build prompt
            context_summary = self._build_context_summary(ctx)
            investigation_prompt = self._get_investigation_prompt(ctx, domain_data)
            full_user_message = f"{context_summary}\n\n{investigation_prompt}"

            # Step 4 — LLM call
            llm_result: AgentFindingLLM = await self.llm.complete(
                system_prompt=self.role_prompt,
                user_message=full_user_message,
                response_schema=AgentFindingLLM,
                incident_id=ctx.incident_id,
            )

            # Step 5 — persist evidence
            evidence_node = EvidenceNode(
                id=str(uuid.uuid4()),
                incident_id=ctx.incident_id,
                agent=self.name,
                evidence_type=llm_result.evidence_type,
                summary=llm_result.summary,
                raw_data={},
                confidence=llm_result.confidence,
                parent_ids=[],
                timestamp=datetime.now(timezone.utc),
                round_number=ctx.investigation_round,
            )
            await self.evidence_store.add_node(evidence_node)

            # Emit evidence event
            await self.event_bus.publish(
                ctx.incident_id,
                {
                    "type": "evidence_added",
                    "payload": evidence_node.model_dump(mode="json"),
                },
            )

            # Step 6 — corroboration-adjusted confidence
            adjusted_confidence = self._adjust_confidence(
                llm_result.confidence, ctx.existing_evidence, llm_result.root_cause_hypothesis
            )

            # Step 7 — build finding
            finding = AgentFinding(
                id=str(uuid.uuid4()),
                incident_id=ctx.incident_id,
                agent=self.name,
                summary=llm_result.summary,
                root_cause_hypothesis=llm_result.root_cause_hypothesis,
                supporting_evidence=[evidence_node.id],
                confidence=adjusted_confidence,
                round_number=ctx.investigation_round,
                timestamp=datetime.now(timezone.utc),
            )

            # Step 7b — cross-agent corroboration boost
            finding = await self._adjust_for_corroboration(finding, ctx)

            await self.event_bus.publish(
                ctx.incident_id,
                {
                    "type": "finding_added",
                    "payload": finding.model_dump(mode="json"),
                },
            )

            # Step 8
            await self._emit_status(ctx.incident_id, AgentStatus.done)

            logger.info(
                "agent.investigate.complete",
                agent=self.name.value,
                incident_id=ctx.incident_id,
                confidence=finding.confidence,
                round=ctx.investigation_round,
            )
            return finding

        except Exception as exc:
            await self._emit_status(ctx.incident_id, AgentStatus.error)
            logger.error(
                "agent.investigate.error",
                agent=self.name.value,
                incident_id=ctx.incident_id,
                error=str(exc),
            )
            raise

    async def challenge(self, finding: AgentFinding, ctx: SwarmContext) -> ChallengeResult:
        self._current_incident_id = ctx.incident_id
        await self._emit_status(ctx.incident_id, AgentStatus.challenging)

        try:
            # Step 2 — gather cited evidence
            evidence_summaries: list[str] = []
            for eid in finding.supporting_evidence:
                node = await self.evidence_store.get_node(eid, finding.incident_id)
                if node:
                    evidence_summaries.append(
                        f"[{node.evidence_type}] {node.summary} (confidence={node.confidence})"
                    )

            evidence_block = "\n".join(evidence_summaries) or "(no evidence available)"

            # Step 3 — challenge prompt
            challenge_prompt = (
                f"You are {self.name.value}. Review the following finding from "
                f"{finding.agent.value}:\n\n"
                f"Finding: {finding.summary}\n"
                f"Root cause hypothesis: {finding.root_cause_hypothesis}\n"
                f"Confidence: {finding.confidence}\n\n"
                f"Here is the raw evidence:\n{evidence_block}\n\n"
                f"Do you AGREE or DISAGREE? Provide detailed reasoning."
            )

            # Step 4 — LLM call
            llm_result: ChallengeResultLLM = await self.llm.complete(
                system_prompt=self.role_prompt,
                user_message=challenge_prompt,
                response_schema=ChallengeResultLLM,
                incident_id=ctx.incident_id,
            )

            # Step 5 — adjust confidence
            if llm_result.verdict == ChallengeVerdict.agree:
                multiplier = 1.15
            else:
                multiplier = 0.7

            revised = min(max(finding.confidence * multiplier, 0.0), 1.0)

            result = ChallengeResult(
                id=str(uuid.uuid4()),
                incident_id=ctx.incident_id,
                challenger=self.name,
                target_finding_id=finding.id,
                verdict=llm_result.verdict,
                reasoning=llm_result.reasoning,
                revised_confidence=round(revised, 4),
                timestamp=datetime.now(timezone.utc),
            )

            # Step 6 — emit
            await self.event_bus.publish(
                ctx.incident_id,
                {
                    "type": "challenge_resolved",
                    "payload": result.model_dump(mode="json"),
                },
            )

            await self._emit_status(ctx.incident_id, AgentStatus.done)

            logger.info(
                "agent.challenge.complete",
                agent=self.name.value,
                incident_id=ctx.incident_id,
                target_agent=finding.agent.value,
                verdict=llm_result.verdict.value,
                revised_confidence=revised,
            )
            return result

        except Exception as exc:
            await self._emit_status(ctx.incident_id, AgentStatus.error)
            logger.error(
                "agent.challenge.error",
                agent=self.name.value,
                incident_id=ctx.incident_id,
                error=str(exc),
            )
            raise

    # ------------------------------------------------------------------
    # Context helpers
    # ------------------------------------------------------------------

    def _build_context_summary(self, ctx: SwarmContext) -> str:
        """
        Constructs a shared context block injected into every agent prompt:
        - Incident title, description, severity
        - Round number
        - Similar past incidents (title + root_cause + resolution, top 3)
        - Summary of evidence from other agents this round (1 sentence per agent)
        """
        lines = [
            "## Incident Context",
            f"**Title:** {ctx.incident_title}",
            f"**Description:** {ctx.incident_description}",
            f"**Severity:** {ctx.severity}",
            f"**Investigation Round:** {ctx.investigation_round}",
        ]

        if ctx.similar_past_incidents:
            lines.append("\n### Similar Past Incidents")
            for past in ctx.similar_past_incidents[:3]:
                lines.append(
                    f"- **{past.title}** — Root cause: {past.root_cause}. "
                    f"Resolution: {past.resolution} (similarity={past.similarity:.2f})"
                )

        if ctx.other_findings:
            lines.append("\n### Other Agent Findings This Round")
            for f in ctx.other_findings:
                lines.append(
                    f"- **{f.agent.value}**: {f.summary} "
                    f"(hypothesis: {f.root_cause_hypothesis}, confidence={f.confidence:.2f})"
                )

        if ctx.existing_evidence:
            lines.append(f"\n### Existing Evidence ({len(ctx.existing_evidence)} nodes)")
            for e in ctx.existing_evidence[-10:]:  # last 10 to avoid prompt overflow
                lines.append(
                    f"- [{e.agent.value}/{e.evidence_type}] {e.summary} "
                    f"(confidence={e.confidence:.2f}, round={e.round_number})"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Confidence adjustment
    # ------------------------------------------------------------------

    def _adjust_confidence(
        self,
        base_confidence: float,
        existing_evidence: List[EvidenceNode],
        hypothesis: str,
    ) -> float:
        """
        Boost confidence when other evidence corroborates the hypothesis.
        Simple keyword overlap heuristic; real systems would use embeddings.
        """
        if not existing_evidence:
            return base_confidence

        hypothesis_lower = hypothesis.lower()
        corroborations = 0
        for ev in existing_evidence:
            summary_lower = ev.summary.lower()
            # Check for meaningful overlap (shared significant words)
            hyp_words = set(hypothesis_lower.split()) - {
                "the", "a", "an", "is", "was", "in", "of", "to", "and", "or", "for",
            }
            ev_words = set(summary_lower.split()) - {
                "the", "a", "an", "is", "was", "in", "of", "to", "and", "or", "for",
            }
            overlap = hyp_words & ev_words
            if len(overlap) >= 2:
                corroborations += 1

        if corroborations > 0:
            from app.config import get_settings
            boost = get_settings().CORROBORATION_BOOST
            adjusted = base_confidence * (boost ** min(corroborations, 3))
        else:
            adjusted = base_confidence

        return min(round(adjusted, 4), 1.0)

    async def _adjust_for_corroboration(
        self, finding: AgentFinding, ctx: SwarmContext
    ) -> AgentFinding:
        """
        Cross-agent corroboration: compare this finding's hypothesis against
        all other agent findings for the same incident and round.
        Uses token-based Jaccard similarity to avoid sentence-transformers dependency.
        If similarity > 0.4, boost confidence × 1.3 (capped at 0.98).
        """
        peer_findings = [
            f for f in ctx.other_findings
            if f.agent != self.name and f.round_number == finding.round_number
        ]
        if not peer_findings:
            return finding

        try:
            def tokenize(text: str) -> set:
                return set(text.lower().replace(".", "").replace(",", "").split()) - {
                    "the", "a", "an", "is", "was", "in", "of", "to", "and", "or", "for", "with", "on", "at", "by"
                }

            my_tokens = tokenize(finding.root_cause_hypothesis)
            boosted = False
            for pf in peer_findings:
                peer_tokens = tokenize(pf.root_cause_hypothesis)
                union = my_tokens.union(peer_tokens)
                if union:
                    sim = len(my_tokens.intersection(peer_tokens)) / len(union)
                    if sim > 0.4:
                        boosted = True
                        logger.info(
                            "agent.corroboration",
                            agent=self.name.value,
                            peer_agent=pf.agent.value,
                            similarity=round(sim, 3),
                            incident_id=finding.incident_id,
                        )

            if boosted:
                new_conf = min(finding.confidence * 1.3, 0.98)
                finding = finding.model_copy(update={"confidence": round(new_conf, 4)})

        except Exception as exc:
            logger.warning(
                "agent.corroboration.error",
                agent=self.name.value,
                error=str(exc),
            )

        return finding

    # ------------------------------------------------------------------
    # Status emission helper
    # ------------------------------------------------------------------

    async def _emit_status(self, incident_id: str, status: AgentStatus):
        await self.event_bus.publish(
            incident_id,
            {
                "type": "agent_status_change",
                "payload": {
                    "agent_id": self.name.value,
                    "status": status.value,
                },
            },
        )

    # ------------------------------------------------------------------
    # Abstract methods — each subclass implements
    # ------------------------------------------------------------------

    @abstractmethod
    async def _fetch_domain_data(self, ctx: SwarmContext) -> dict:
        """Each subclass fetches its specific data (logs, metrics, deployments)."""
        ...

    @abstractmethod
    def _get_investigation_prompt(self, ctx: SwarmContext, domain_data: dict) -> str:
        """Each subclass builds its specific investigation prompt."""
        ...
