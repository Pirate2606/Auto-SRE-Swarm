import structlog

from app.models import AgentName, PastIncident, EvidenceNode
from agents.base import SwarmContext
from services.event_bus import get_event_bus
from services.evidence_store import EvidenceStore
from services.llm import AzureOpenAIClient
from services.memory_store import IncidentMemoryStore
from services.mock_cloud import MockCloudService

logger = structlog.get_logger(__name__)


class IncidentCommander:
    """
    Adaptive orchestrator — not an agent that calls the LLM for routing.
    Routing decisions are made by the LangGraph conditional edges.
    The Commander's role is: enriching context, overrides, and P1 fast-path.
    """

    def __init__(
        self,
        llm: AzureOpenAIClient,
        evidence_store: EvidenceStore,
        memory_store: IncidentMemoryStore,
    ):
        self.llm = llm
        self.evidence_store = evidence_store
        self.memory_store = memory_store
        self.event_bus = get_event_bus()

    async def enrich_dispatch_context(self, state: dict) -> SwarmContext:
        """
        Before dispatching agents, build enriched SwarmContext:
        - Pull existing evidence (for rounds > 1)
        - Add similar past incidents
        - Add round-specific focus areas
        """
        incident_id = state["incident_id"]
        investigation_round = state.get("investigation_round", 1)

        # Pull existing evidence for subsequent rounds
        existing_evidence: list[EvidenceNode] = []
        if investigation_round > 1:
            existing_evidence = await self.evidence_store.get_incident_graph(incident_id)

        # Pull similar past incidents
        similar = state.get("similar_past_incidents", [])

        ctx = SwarmContext(
            incident_id=incident_id,
            incident_title=state["title"],
            incident_description=state["description"],
            severity=state["severity"],
            investigation_round=investigation_round,
            existing_evidence=existing_evidence,
            other_findings=state.get("agent_findings", []),
            similar_past_incidents=similar,
            mock_cloud=MockCloudService(),
        )

        logger.info(
            "commander.context_enriched",
            incident_id=incident_id,
            round=investigation_round,
            evidence_count=len(existing_evidence),
            similar_count=len(similar),
        )

        return ctx

    async def handle_p1_override(self, state: dict) -> bool:
        """
        If severity == P1 and round >= 2: allow proceeding with confidence < 0.7.
        Emit a commander_override event to the event bus.
        Returns True if override was applied.
        """
        severity = state.get("severity", "")
        investigation_round = state.get("investigation_round", 1)
        confidence = state.get("consensus_confidence", 0.0)

        if severity == "P1" and investigation_round >= 2 and confidence < 0.7:
            await self.event_bus.publish(
                state["incident_id"],
                {
                    "type": "commander_override",
                    "payload": {
                        "reason": f"P1 override: proceeding with confidence {confidence:.2f} at round {investigation_round}",
                        "incident_id": state["incident_id"],
                        "confidence": confidence,
                        "round": investigation_round,
                    },
                },
            )

            logger.warning(
                "commander.p1_override",
                incident_id=state["incident_id"],
                confidence=confidence,
                round=investigation_round,
            )
            return True

        return False
