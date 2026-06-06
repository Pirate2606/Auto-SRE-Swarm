import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import numpy as np
import structlog

from app.config import get_settings
from app.models import (
    AgentFinding,
    AgentName,
    ChallengeResult,
    Conflict,
    ConsensusResult,
    Hypothesis,
)
from agents.base import SwarmAgent, SwarmContext
from db.database import get_consensus_container
from services.event_bus import get_event_bus
from services.llm import AzureOpenAIClient

logger = structlog.get_logger(__name__)


class ConsensusEngine:
    """
    Probabilistic evidence fusion engine.
    Does NOT use an LLM for synthesis — pure algorithmic aggregation.
    LLM is only used for conflict narrative generation and hypothesis summarisation.
    """

    def __init__(self, llm: AzureOpenAIClient):
        self.llm = llm
        self.event_bus = get_event_bus()
        self._model = None
        self._model_lock = asyncio.Lock()

    def _cosine_similarity_matrix(self, texts: List[str]) -> np.ndarray:
        n = len(texts)
        sim_matrix = np.zeros((n, n))
        
        def tokenize(text: str) -> set:
            words = text.lower().replace(".", "").replace(",", "").split()
            tokens = set()
            for w in words:
                if w in {"the", "a", "an", "is", "was", "in", "of", "to", "and", "or", "for", "with", "on", "at", "by", "this", "that", "it"}:
                    continue
                # SRE Domain Synonym mappings
                if w in {"oom", "memory", "ram", "saturation", "leak", "heap"}:
                    tokens.add("memory_issue")
                elif w in {"traffic", "load", "rps", "spike", "request", "requests", "concurrency"}:
                    tokens.add("traffic_issue")
                elif w in {"deployment", "version", "release", "deploy", "change", "redeploy"}:
                    tokens.add("deploy_issue")
                elif w in {"db", "database", "sql", "query", "connection", "pool"}:
                    tokens.add("database_issue")
                else:
                    tokens.add(w)
            return tokens

        token_sets = [tokenize(t) for t in texts]
        
        for i in range(n):
            for j in range(n):
                if i == j:
                    sim_matrix[i][j] = 1.0
                else:
                    set_a = token_sets[i]
                    set_b = token_sets[j]
                    union = set_a.union(set_b)
                    if union:
                        sim_matrix[i][j] = len(set_a.intersection(set_b)) / len(union)
                    else:
                        sim_matrix[i][j] = 0.0
        return sim_matrix

    # ------------------------------------------------------------------
    # Core fusion pipeline
    # ------------------------------------------------------------------

    async def fuse(
        self,
        findings: list[AgentFinding],
        incident_id: str,
        round_number: int,
    ) -> ConsensusResult:
        """
        Full fusion pipeline:
        1. CLUSTER — group findings by semantic similarity of root_cause_hypothesis
        2. WEIGHT — score each finding
        3. DETECT CONFLICTS
        4. COMPUTE CONFIDENCE
        5. BUILD HYPOTHESIS
        6. EMIT events
        7. WRITE consensus result to DB
        8. Return ConsensusResult
        """
        settings = get_settings()

        if not findings:
            empty_hyp = Hypothesis(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                title="No findings available",
                description="No agent findings were produced in this round.",
                confidence=0.0,
                supporting_finding_ids=[],
                round_number=round_number,
                timestamp=datetime.now(timezone.utc),
            )
            return ConsensusResult(
                incident_id=incident_id,
                hypothesis=empty_hyp,
                confidence=0.0,
                conflicts=[],
                round_number=round_number,
                evidence_chain=[],
                timestamp=datetime.now(timezone.utc),
            )

        # ---- Step 1: CLUSTER ----
        hypotheses_texts = [f.root_cause_hypothesis for f in findings]
        sim_matrix = self._cosine_similarity_matrix(hypotheses_texts)

        clusters, cluster_assignments = self._cluster_findings(
            findings, sim_matrix, threshold=0.65
        )

        logger.info(
            "consensus.clustered",
            incident_id=incident_id,
            round=round_number,
            num_findings=len(findings),
            num_clusters=len(clusters),
        )

        # ---- Step 2: WEIGHT ----
        weights = self._compute_weights(findings, clusters, cluster_assignments, round_number)

        # ---- Step 3: DETECT CONFLICTS ----
        hard_conflicts, soft_conflicts = await self._detect_all_conflicts(
            findings, sim_matrix
        )

        # Emit hard conflict events
        for conflict in hard_conflicts:
            await self.event_bus.publish(
                incident_id,
                {
                    "type": "conflict_detected",
                    "payload": conflict.model_dump(mode="json"),
                },
            )

        # Apply soft conflict penalty: weight the lower-confidence hypothesis at 0.7×
        for sc in soft_conflicts:
            idx_a = next(
                (i for i, f in enumerate(findings) if f.agent == sc.agent_a), None
            )
            idx_b = next(
                (i for i, f in enumerate(findings) if f.agent == sc.agent_b), None
            )
            if idx_a is not None and idx_b is not None:
                if findings[idx_a].confidence < findings[idx_b].confidence:
                    weights[idx_a] *= 0.7
                else:
                    weights[idx_b] *= 0.7

        # ---- Step 4: COMPUTE CONFIDENCE ----
        # Find the winning cluster (highest total weight)
        cluster_total_weights: Dict[int, float] = {}
        for i, ci in enumerate(cluster_assignments):
            cluster_total_weights[ci] = cluster_total_weights.get(ci, 0.0) + weights[i]

        winning_cluster_id = max(cluster_total_weights, key=cluster_total_weights.get)
        winning_indices = [
            i for i, ci in enumerate(cluster_assignments) if ci == winning_cluster_id
        ]
        winning_findings = [findings[i] for i in winning_indices]
        winning_weights = [weights[i] for i in winning_indices]

        # H_confidence = Σ(weight_i × confidence_i) / Σ(weight_i)
        total_w = sum(winning_weights)
        if total_w > 0:
            h_confidence = sum(
                w * findings[i].confidence
                for i, w in zip(winning_indices, winning_weights)
            ) / total_w
        else:
            h_confidence = 0.0

        h_confidence = round(min(h_confidence, 1.0), 4)

        # ---- Step 5: BUILD HYPOTHESIS ----
        hypothesis = await self.generate_consensus_hypothesis(
            winning_findings, incident_id, round_number, h_confidence
        )

        # Collect evidence chain (ordered evidence node IDs from all winning findings)
        evidence_chain: list[str] = []
        for f in winning_findings:
            for eid in f.supporting_evidence:
                if eid not in evidence_chain:
                    evidence_chain.append(eid)

        all_conflicts = hard_conflicts + soft_conflicts

        result = ConsensusResult(
            incident_id=incident_id,
            hypothesis=hypothesis,
            confidence=h_confidence,
            conflicts=all_conflicts,
            round_number=round_number,
            evidence_chain=evidence_chain,
            timestamp=datetime.now(timezone.utc),
        )

        # ---- Step 6: EMIT events ----
        # Confidence update
        await self.event_bus.publish(
            incident_id,
            {
                "type": "confidence_update",
                "payload": {
                    "round": round_number,
                    "confidence": h_confidence,
                    "trend": self._compute_trend(h_confidence, round_number),
                },
            },
        )

        if h_confidence >= settings.CONFIDENCE_THRESHOLD:
            await self.event_bus.publish(
                incident_id,
                {
                    "type": "consensus_reached",
                    "payload": result.model_dump(mode="json"),
                },
            )
            logger.info(
                "consensus.reached",
                incident_id=incident_id,
                confidence=h_confidence,
                round=round_number,
            )
        elif round_number < settings.MAX_INVESTIGATION_ROUNDS:
            await self.event_bus.publish(
                incident_id,
                {
                    "type": "reinvestigation_needed",
                    "payload": {
                        "reason": f"Confidence {h_confidence:.2f} below threshold {settings.CONFIDENCE_THRESHOLD}",
                        "target_agents": [f.agent.value for f in findings],
                        "round": round_number + 1,
                    },
                },
            )
            logger.info(
                "consensus.reinvestigation_needed",
                incident_id=incident_id,
                confidence=h_confidence,
                round=round_number,
            )
        else:
            logger.warning(
                "consensus.max_rounds_reached",
                incident_id=incident_id,
                confidence=h_confidence,
                round=round_number,
            )

        # ---- Step 7: WRITE to DB ----
        await self._persist_consensus(result)

        return result

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    def _cluster_findings(
        self,
        findings: list[AgentFinding],
        sim_matrix: np.ndarray,
        threshold: float = 0.65,
    ) -> Tuple[Dict[int, List[int]], List[int]]:
        """
        Greedy single-linkage clustering: assign each finding to the first
        cluster whose centroid similarity exceeds `threshold`, or create a new one.
        Returns: (clusters dict {cluster_id: [indices]}, assignment list)
        """
        n = len(findings)
        cluster_assignments = [-1] * n
        clusters: Dict[int, List[int]] = {}
        next_cluster = 0

        for i in range(n):
            best_cluster = -1
            best_sim = -1.0
            for cid, members in clusters.items():
                avg_sim = float(np.mean([sim_matrix[i][j] for j in members]))
                if avg_sim >= threshold and avg_sim > best_sim:
                    best_cluster = cid
                    best_sim = avg_sim

            if best_cluster >= 0:
                clusters[best_cluster].append(i)
                cluster_assignments[i] = best_cluster
            else:
                clusters[next_cluster] = [i]
                cluster_assignments[i] = next_cluster
                next_cluster += 1

        return clusters, cluster_assignments

    # ------------------------------------------------------------------
    # Weighting
    # ------------------------------------------------------------------

    def _compute_weights(
        self,
        findings: list[AgentFinding],
        clusters: Dict[int, List[int]],
        cluster_assignments: List[int],
        round_number: int,
    ) -> List[float]:
        """
        weight_i = confidence_i × evidence_strength_i × corroboration_factor_i
        evidence_strength = len(supporting_evidence) / 5.0, capped at 1.0
        corroboration_factor = 1 + (0.3 × count of OTHER agents in same cluster)
        Temporal weighting: × (1.0 + 0.1 × round_number)
        """
        weights = []
        for i, f in enumerate(findings):
            evidence_strength = min(len(f.supporting_evidence) / 5.0, 1.0)

            cluster_id = cluster_assignments[i]
            cluster_size = len(clusters.get(cluster_id, []))
            other_in_cluster = max(cluster_size - 1, 0)
            corroboration_factor = 1.0 + (0.3 * other_in_cluster)

            temporal_weight = 1.0 + (0.1 * round_number)

            w = f.confidence * evidence_strength * corroboration_factor * temporal_weight
            weights.append(w)

        return weights

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    async def detect_conflicts(self, findings: list[AgentFinding]) -> list[Conflict]:
        """Return hard conflicts (cosine similarity < 0.4)."""
        if len(findings) < 2:
            return []
        texts = [f.root_cause_hypothesis for f in findings]
        sim_matrix = self._cosine_similarity_matrix(texts)
        hard, _ = self._extract_conflicts(findings, sim_matrix)
        return hard

    async def _detect_all_conflicts(
        self, findings: list[AgentFinding], sim_matrix: np.ndarray
    ) -> Tuple[List[Conflict], List[Conflict]]:
        """Detect both hard and soft conflicts from a precomputed similarity matrix."""
        return self._extract_conflicts(findings, sim_matrix)

    def _extract_conflicts(
        self, findings: list[AgentFinding], sim_matrix: np.ndarray
    ) -> Tuple[List[Conflict], List[Conflict]]:
        hard_conflicts: List[Conflict] = []
        soft_conflicts: List[Conflict] = []

        n = len(findings)
        for i in range(n):
            for j in range(i + 1, n):
                if findings[i].agent == findings[j].agent:
                    continue
                sim = float(sim_matrix[i][j])
                if sim < 0.4:
                    # Hard conflict
                    evidence_ids = list(
                        set(findings[i].supporting_evidence + findings[j].supporting_evidence)
                    )
                    hard_conflicts.append(
                        Conflict(
                            id=str(uuid.uuid4()),
                            agent_a=findings[i].agent,
                            agent_b=findings[j].agent,
                            position_a=findings[i].root_cause_hypothesis,
                            position_b=findings[j].root_cause_hypothesis,
                            evidence_ids=evidence_ids,
                        )
                    )
                    logger.info(
                        "consensus.hard_conflict",
                        agent_a=findings[i].agent.value,
                        agent_b=findings[j].agent.value,
                        similarity=round(sim, 3),
                    )
                elif sim < 0.65:
                    # Soft conflict
                    evidence_ids = list(
                        set(findings[i].supporting_evidence + findings[j].supporting_evidence)
                    )
                    soft_conflicts.append(
                        Conflict(
                            id=str(uuid.uuid4()),
                            agent_a=findings[i].agent,
                            agent_b=findings[j].agent,
                            position_a=findings[i].root_cause_hypothesis,
                            position_b=findings[j].root_cause_hypothesis,
                            evidence_ids=evidence_ids,
                        )
                    )
                    logger.warning(
                        "consensus.soft_conflict",
                        agent_a=findings[i].agent.value,
                        agent_b=findings[j].agent.value,
                        similarity=round(sim, 3),
                    )

        return hard_conflicts, soft_conflicts

    # ------------------------------------------------------------------
    # Hypothesis generation (LLM-assisted)
    # ------------------------------------------------------------------

    async def generate_consensus_hypothesis(
        self,
        cluster: list[AgentFinding],
        incident_id: str,
        round_number: int,
        confidence: float,
    ) -> Hypothesis:
        """
        Use LLM to generate a clean, concise hypothesis statement from the
        winning cluster of findings.
        """
        findings_block = "\n".join(
            f"- [{f.agent.value}] {f.root_cause_hypothesis} (confidence={f.confidence:.2f})"
            for f in cluster
        )

        try:
            from pydantic import BaseModel as _BM

            class _HypothesisLLM(_BM):
                title: str
                description: str

            result: _HypothesisLLM = await self.llm.complete(
                system_prompt=(
                    "You are a consensus synthesis engine. Given multiple agent findings "
                    "about an incident, produce a single clear root cause hypothesis."
                ),
                user_message=(
                    f"The following agents have investigated the incident:\n\n"
                    f"{findings_block}\n\n"
                    f"Write a single clear root cause hypothesis.\n"
                    f"- title: a concise title (max 100 chars)\n"
                    f"- description: 2-3 sentences explaining the root cause"
                ),
                response_schema=_HypothesisLLM,
                incident_id=incident_id,
            )

            return Hypothesis(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                title=result.title,
                description=result.description,
                confidence=confidence,
                supporting_finding_ids=[f.id for f in cluster],
                round_number=round_number,
                timestamp=datetime.now(timezone.utc),
            )

        except Exception as exc:
            # Fallback: use the highest-confidence finding as the hypothesis
            logger.warning(
                "consensus.hypothesis_llm_fallback",
                incident_id=incident_id,
                error=str(exc),
            )
            best = max(cluster, key=lambda f: f.confidence)
            return Hypothesis(
                id=str(uuid.uuid4()),
                incident_id=incident_id,
                title=best.root_cause_hypothesis[:100],
                description=best.summary,
                confidence=confidence,
                supporting_finding_ids=[f.id for f in cluster],
                round_number=round_number,
                timestamp=datetime.now(timezone.utc),
            )

    # ------------------------------------------------------------------
    # Challenge round
    # ------------------------------------------------------------------

    async def request_challenge_round(
        self,
        conflict: Conflict,
        agents: Dict[AgentName, SwarmAgent],
        ctx: SwarmContext,
        findings: list[AgentFinding],
    ) -> list[ChallengeResult]:
        """
        For each hard conflict:
        - The challenger is the agent whose hypothesis is NOT the dominant one.
        - Call challenger.challenge(target_finding, ctx)
        - Collect results.
        """
        results: List[ChallengeResult] = []

        # Determine dominant agent (higher confidence)
        finding_a = next((f for f in findings if f.agent == conflict.agent_a), None)
        finding_b = next((f for f in findings if f.agent == conflict.agent_b), None)

        if not finding_a or not finding_b:
            return results

        if finding_a.confidence >= finding_b.confidence:
            dominant_finding = finding_a
            challenger_agent_name = conflict.agent_b
        else:
            dominant_finding = finding_b
            challenger_agent_name = conflict.agent_a

        challenger = agents.get(challenger_agent_name)
        if challenger is None:
            logger.warning(
                "consensus.challenge.no_agent",
                challenger=challenger_agent_name.value,
            )
            return results

        try:
            challenge_result = await challenger.challenge(dominant_finding, ctx)
            results.append(challenge_result)

            logger.info(
                "consensus.challenge.complete",
                challenger=challenger_agent_name.value,
                target=dominant_finding.agent.value,
                verdict=challenge_result.verdict.value,
                revised_confidence=challenge_result.revised_confidence,
            )
        except Exception as exc:
            logger.error(
                "consensus.challenge.error",
                challenger=challenger_agent_name.value,
                error=str(exc),
            )

        return results

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_consensus(self, result: ConsensusResult):
        try:
            container = await get_consensus_container()
            doc = {
                "id": str(uuid.uuid4()),
                "incident_id": result.incident_id,
                "hypothesis": result.hypothesis.model_dump(mode="json"),
                "confidence": result.confidence,
                "conflicts": [c.model_dump(mode="json") for c in result.conflicts],
                "round_number": result.round_number,
                "evidence_chain": result.evidence_chain,
                "timestamp": result.timestamp.isoformat(),
            }
            await container.upsert_item(doc)
        except Exception as exc:
            logger.error(
                "consensus.persist_error",
                incident_id=result.incident_id,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _previous_confidence: Dict[str, float] = {}

    def _compute_trend(self, confidence: float, round_number: int) -> str:
        key = f"r{round_number}"
        prev = self._previous_confidence.get(key)
        self._previous_confidence[key] = confidence

        if prev is None:
            return "stable"
        if confidence > prev + 0.05:
            return "increasing"
        elif confidence < prev - 0.05:
            return "decreasing"
        return "stable"
