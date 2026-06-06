import json
import uuid
from datetime import datetime, timezone

import structlog
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from app.models import (
    AgentName,
    AgentStatus,
    AgentStatusEntry,
    ApprovalStatus,
    Incident,
    IncidentCreate,
    IncidentCreateResponse,
    IncidentStatus,
    IncidentSummary,
    PastIncident,
    SwarmStatus,
)
from app.deps import get_evidence_store, get_memory_store
from orchestrator.manager import start_investigation
from db.database import (
    get_incidents_container,
    get_consensus_container,
    get_postmortems_container,
)
from services.event_bus import get_event_bus

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")


# start_investigation is imported from orchestrator.manager and called directly

# -----------------------------------------------------------------------
# POST /incidents
# -----------------------------------------------------------------------
@router.post("/incidents", status_code=201, response_model=IncidentCreateResponse)
async def create_incident(body: IncidentCreate, background_tasks: BackgroundTasks):
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    doc = {
        "id": incident_id,
        "title": body.title,
        "description": body.description,
        "severity": body.severity.value,
        "source": body.source,
        "metadata": body.metadata,
        "status": IncidentStatus.investigating.value,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "investigation_round": 0,
        "consensus_confidence": None,
        "agent_statuses": {},
    }

    container = await get_incidents_container()
    await container.upsert_item(doc)

    # Query memory store for similar past incidents
    memory_store = get_memory_store()
    try:
        similar = await memory_store.recall_similar(body.description, top_k=3)
    except Exception:
        similar = []

    # Build initial workflow state
    initial_state = {
        "incident_id": incident_id,
        "title": body.title,
        "description": body.description,
        "severity": body.severity.value,
        "evidence_nodes": [],
        "agent_findings": [],
        "active_agents": [],
        "challenge_results": [],
        "hypotheses": [],
        "consensus_confidence": 0.0,
        "conflicts": [],
        "investigation_round": 0,
        "proposed_actions": [],
        "approval_status": ApprovalStatus.pending,
        "approval_requests": [],
        "similar_past_incidents": similar,
        "status": IncidentStatus.investigating,
        "postmortem": None,
        "messages": [],
        "timeline": [],
        "safety_result": None,
    }

    background_tasks.add_task(start_investigation, incident_id, body.description)

    agents = [
        AgentStatusEntry(name=n, status=AgentStatus.idle)
        for n in [AgentName.log_forensics, AgentName.telemetry_intel, AgentName.deployment_intel]
    ]

    logger.info("incident.created", incident_id=incident_id, severity=body.severity.value)

    return IncidentCreateResponse(
        id=incident_id,
        status=IncidentStatus.investigating,
        swarm=SwarmStatus(round=0, agents=agents, consensus_confidence=None),
        similar_past_incidents=similar,
    )


# -----------------------------------------------------------------------
# GET /incidents
# -----------------------------------------------------------------------
@router.get("/incidents", response_model=list[IncidentSummary])
async def list_incidents(skip: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100)):
    container = await get_incidents_container()

    query = (
        "SELECT c.id, c.title, c.severity, c.status, c.created_at, c.consensus_confidence "
        "FROM c ORDER BY c.created_at DESC OFFSET @skip LIMIT @limit"
    )
    parameters = [
        {"name": "@skip", "value": skip},
        {"name": "@limit", "value": limit},
    ]

    results = []
    async for doc in container.query_items(query=query, parameters=parameters):
        results.append(
            IncidentSummary(
                id=doc["id"], title=doc["title"],
                severity=doc["severity"], status=doc["status"],
                created_at=doc["created_at"],
                consensus_confidence=doc.get("consensus_confidence"),
            )
        )

    return results


# -----------------------------------------------------------------------
# GET /incidents/{id}
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}", response_model=Incident)
async def get_incident(incident_id: str):
    container = await get_incidents_container()
    try:
        doc = await container.read_item(item=incident_id, partition_key=incident_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    return Incident(
        id=doc["id"], title=doc["title"], description=doc["description"],
        severity=doc["severity"], source=doc["source"],
        metadata=doc.get("metadata", {}),
        status=doc["status"],
        created_at=doc["created_at"], updated_at=doc["updated_at"],
        agent_statuses=doc.get("agent_statuses", {}),
        investigation_round=doc.get("investigation_round", 0),
        consensus_confidence=doc.get("consensus_confidence"),
    )


# -----------------------------------------------------------------------
# PATCH /incidents/{id}
# -----------------------------------------------------------------------
@router.patch("/incidents/{incident_id}", response_model=Incident)
async def update_incident(incident_id: str, updates: dict):
    allowed = {"severity", "status"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        raise HTTPException(status_code=422, detail="No valid fields to update")

    container = await get_incidents_container()

    # Read-modify-upsert
    try:
        doc = await container.read_item(item=incident_id, partition_key=incident_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")

    for k, v in filtered.items():
        doc[k] = v
    doc["updated_at"] = datetime.now(timezone.utc).isoformat()

    await container.upsert_item(doc)

    return await get_incident(incident_id)


# -----------------------------------------------------------------------
# GET /incidents/{id}/evidence
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/evidence")
async def get_evidence(incident_id: str):
    store = get_evidence_store()
    nodes = await store.get_incident_graph(incident_id)
    return [n.model_dump(mode="json") for n in nodes]


# -----------------------------------------------------------------------
# GET /incidents/{id}/evidence/{nid}
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/evidence/{node_id}")
async def get_evidence_node(incident_id: str, node_id: str):
    store = get_evidence_store()
    node = await store.get_node(node_id, incident_id)
    if not node or node.incident_id != incident_id:
        raise HTTPException(status_code=404, detail=f"Evidence node {node_id} not found")
    return node.model_dump(mode="json")


# -----------------------------------------------------------------------
# GET /incidents/{id}/consensus
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/consensus")
async def get_consensus(incident_id: str):
    container = await get_consensus_container()

    query = (
        "SELECT * FROM c WHERE c.incident_id = @incident_id "
        "ORDER BY c.round_number DESC OFFSET 0 LIMIT 1"
    )
    parameters = [{"name": "@incident_id", "value": incident_id}]

    row = None
    async for doc in container.query_items(query=query, parameters=parameters, partition_key=incident_id):
        row = doc
        break

    if not row:
        raise HTTPException(status_code=404, detail="No consensus result yet")
    return {
        "incident_id": row["incident_id"],
        "hypothesis": row.get("hypothesis", {}),
        "confidence": row["confidence"],
        "conflicts": row.get("conflicts", []),
        "round_number": row["round_number"],
        "evidence_chain": row.get("evidence_chain", []),
        "timestamp": row["timestamp"],
    }


# -----------------------------------------------------------------------
# GET /incidents/{id}/conflicts
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/conflicts")
async def get_conflicts(incident_id: str):
    container = await get_consensus_container()

    query = (
        "SELECT c.conflicts FROM c WHERE c.incident_id = @incident_id "
        "ORDER BY c.round_number DESC OFFSET 0 LIMIT 1"
    )
    parameters = [{"name": "@incident_id", "value": incident_id}]

    async for doc in container.query_items(query=query, parameters=parameters, partition_key=incident_id):
        return doc.get("conflicts", [])

    return []


# -----------------------------------------------------------------------
# GET /incidents/{id}/agents
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/agents")
async def get_agents(incident_id: str):
    container = await get_incidents_container()
    try:
        doc = await container.read_item(item=incident_id, partition_key=incident_id)
    except CosmosResourceNotFoundError:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    return doc.get("agent_statuses", {})


# -----------------------------------------------------------------------
# GET /incidents/{id}/timeline
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/timeline")
async def get_timeline(incident_id: str):
    container = await get_incidents_container()
    try:
        doc = await container.read_item(item=incident_id, partition_key=incident_id)
        return doc.get("timeline", [])
    except Exception as exc:
        logger.warning("routes.get_timeline_error", incident_id=incident_id, error=str(exc))
    return []


# -----------------------------------------------------------------------
# GET /incidents/{id}/postmortem
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/postmortem")
async def get_postmortem(incident_id: str):
    container = await get_postmortems_container()

    query = "SELECT * FROM c WHERE c.incident_id = @incident_id"
    parameters = [{"name": "@incident_id", "value": incident_id}]

    row = None
    async for doc in container.query_items(query=query, parameters=parameters, partition_key=incident_id):
        row = doc
        break

    if not row:
        raise HTTPException(status_code=404, detail="Postmortem not yet generated")
    return {
        "incident_id": row["incident_id"],
        "executive_summary": row["executive_summary"],
        "timeline": row.get("timeline", []),
        "root_cause": row["root_cause"],
        "contributing_factors": row.get("contributing_factors", []),
        "remediation_actions": row.get("remediation_actions", []),
        "prevention_recommendations": row.get("prevention_recommendations", []),
        "recurrence_risk": row["recurrence_risk"],
        "generated_at": row["generated_at"],
    }


# -----------------------------------------------------------------------
# GET /memory/similar
# -----------------------------------------------------------------------
@router.get("/memory/similar")
async def query_similar(q: str = Query(..., min_length=3), top_k: int = Query(3, ge=1, le=20)):
    memory_store = get_memory_store()
    results = await memory_store.recall_similar(q, top_k=top_k)
    return [r.model_dump(mode="json") for r in results]


# -----------------------------------------------------------------------
# GET /health
# -----------------------------------------------------------------------
@router.get("/health")
async def health_check():
    from app.deps import get_llm
    try:
        llm = get_llm()
        llm_ok = await llm.health_check()
    except Exception:
        llm_ok = False
    return {"status": "ok", "llm": llm_ok}
