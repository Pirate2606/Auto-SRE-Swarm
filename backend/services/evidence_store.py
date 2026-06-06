"""
EvidenceStore backed by Azure Cosmos DB (``Evidence`` container).

All public methods are async and use the ``azure-cosmos`` async interfaces.
"""

import structlog
from typing import List, Tuple, Optional

from db.database import get_evidence_container
from app.models import EvidenceNode, AgentName

logger = structlog.get_logger(__name__)


class EvidenceStoreError(Exception):
    pass


class EvidenceStore:
    """Manages EvidenceNode documents in the Cosmos DB *Evidence* container."""

    # ── helpers ────────────────────────────────────────────────────

    @staticmethod
    def _node_to_doc(node: EvidenceNode) -> dict:
        """Convert a Pydantic EvidenceNode to a Cosmos-friendly dict.

        Cosmos requires a string ``id`` field and the partition key
        (``incident_id``) at the top level — both already present on
        the model.  Enum values and datetimes are serialised via
        Pydantic's ``model_dump(mode="json")``.
        """
        return node.model_dump(mode="json")

    @staticmethod
    def _doc_to_node(doc: dict) -> EvidenceNode:
        """Reconstruct an EvidenceNode from a Cosmos document."""
        return EvidenceNode(
            id=doc["id"],
            incident_id=doc["incident_id"],
            agent=AgentName(doc["agent"]),
            evidence_type=doc["evidence_type"],
            summary=doc["summary"],
            raw_data=doc["raw_data"],
            confidence=doc["confidence"],
            parent_ids=doc.get("parent_ids", []),
            timestamp=doc["timestamp"],
            round_number=doc["round_number"],
        )

    # ── CRUD ──────────────────────────────────────────────────────

    async def add_node(self, node: EvidenceNode) -> EvidenceNode:
        """Upsert an EvidenceNode into the Evidence container."""
        container = await get_evidence_container()
        try:
            doc = self._node_to_doc(node)
            await container.upsert_item(doc)
            logger.debug("evidence.upsert", node_id=node.id, incident_id=node.incident_id)
            return node
        except Exception as e:
            raise EvidenceStoreError(f"Cosmos upsert failed: {e}") from e

    async def get_node(self, node_id: str, incident_id: str) -> Optional[EvidenceNode]:
        """Read a single EvidenceNode by id.

        ``incident_id`` is required because it is the partition key.
        """
        container = await get_evidence_container()
        try:
            doc = await container.read_item(item=node_id, partition_key=incident_id)
            return self._doc_to_node(doc)
        except Exception:
            return None

    async def get_incident_graph(self, incident_id: str) -> List[EvidenceNode]:
        """Return every EvidenceNode for the given incident.

        Uses a cross-partition-safe query scoped to the partition key
        ``incident_id``.
        """
        container = await get_evidence_container()
        try:
            query = "SELECT * FROM c WHERE c.incident_id = @incident_id"
            parameters = [{"name": "@incident_id", "value": incident_id}]
            items = container.query_items(
                query=query,
                parameters=parameters,
                partition_key=incident_id,
            )
            nodes: List[EvidenceNode] = []
            async for doc in items:
                nodes.append(self._doc_to_node(doc))
            return nodes
        except Exception as e:
            raise EvidenceStoreError(f"Cosmos query failed: {e}") from e

    async def get_nodes_by_agent(self, incident_id: str, agent: AgentName) -> List[EvidenceNode]:
        """Return evidence nodes for a specific agent within an incident."""
        container = await get_evidence_container()
        try:
            query = (
                "SELECT * FROM c "
                "WHERE c.incident_id = @incident_id AND c.agent = @agent"
            )
            parameters = [
                {"name": "@incident_id", "value": incident_id},
                {"name": "@agent", "value": agent.value},
            ]
            items = container.query_items(
                query=query,
                parameters=parameters,
                partition_key=incident_id,
            )
            nodes: List[EvidenceNode] = []
            async for doc in items:
                nodes.append(self._doc_to_node(doc))
            return nodes
        except Exception as e:
            raise EvidenceStoreError(f"Cosmos query failed: {e}") from e

    async def get_nodes_by_round(self, incident_id: str, round_number: int) -> List[EvidenceNode]:
        """Return evidence nodes for a specific investigation round."""
        container = await get_evidence_container()
        try:
            query = (
                "SELECT * FROM c "
                "WHERE c.incident_id = @incident_id AND c.round_number = @round"
            )
            parameters = [
                {"name": "@incident_id", "value": incident_id},
                {"name": "@round", "value": round_number},
            ]
            items = container.query_items(
                query=query,
                parameters=parameters,
                partition_key=incident_id,
            )
            nodes: List[EvidenceNode] = []
            async for doc in items:
                nodes.append(self._doc_to_node(doc))
            return nodes
        except Exception as e:
            raise EvidenceStoreError(f"Cosmos query failed: {e}") from e

    async def add_edge(self, parent_id: str, child_id: str, incident_id: str) -> None:
        """Append *parent_id* to the child node's ``parent_ids`` list.

        Uses a read-modify-upsert pattern on the Evidence container.
        ``incident_id`` is needed as the partition key for the point-read.
        """
        container = await get_evidence_container()
        try:
            doc = await container.read_item(item=child_id, partition_key=incident_id)
            parent_ids: list = doc.get("parent_ids", [])
            if parent_id not in parent_ids:
                parent_ids.append(parent_id)
                doc["parent_ids"] = parent_ids
                await container.upsert_item(doc)
        except Exception as e:
            raise EvidenceStoreError(f"Cosmos add_edge failed: {e}") from e

    async def get_subgraph(self, root_id: str, incident_id: str) -> List[EvidenceNode]:
        """BFS traversal starting from *root_id* following parent→child edges."""
        all_nodes = await self.get_incident_graph(incident_id)
        if not all_nodes:
            return []

        children_map: dict[str, list[str]] = {}
        for n in all_nodes:
            for pid in n.parent_ids:
                children_map.setdefault(pid, []).append(n.id)

        visited: set[str] = set()
        queue = [root_id]
        result: List[EvidenceNode] = []
        node_map = {n.id: n for n in all_nodes}

        while queue:
            curr_id = queue.pop(0)
            if curr_id in visited:
                continue
            visited.add(curr_id)
            if curr_id in node_map:
                result.append(node_map[curr_id])
                for child_id in children_map.get(curr_id, []):
                    if child_id not in visited:
                        queue.append(child_id)

        return result

    async def get_conflict_candidates(self, incident_id: str) -> List[Tuple[EvidenceNode, EvidenceNode]]:
        """Identify pairs of evidence nodes that may represent conflicting signals."""
        nodes = await self.get_incident_graph(incident_id)
        by_round: dict[int, list[EvidenceNode]] = {}
        for n in nodes:
            by_round.setdefault(n.round_number, []).append(n)

        candidates: List[Tuple[EvidenceNode, EvidenceNode]] = []
        for _r_num, r_nodes in by_round.items():
            for i in range(len(r_nodes)):
                for j in range(i + 1, len(r_nodes)):
                    n1 = r_nodes[i]
                    n2 = r_nodes[j]
                    if n1.agent != n2.agent:
                        if n1.evidence_type != n2.evidence_type or abs(n1.confidence - n2.confidence) > 0.3:
                            candidates.append((n1, n2))
        return candidates
