import json
from datetime import datetime, timezone

import structlog
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import APIRouter, HTTPException

from app.models import ApprovalDecision, ApprovalRequest, ApprovalStatus
# get_workflow removed as we migrated from LangGraph to AutoGen GroupChat
from db.database import get_approvals_container
from services.event_bus import get_event_bus

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")


# -----------------------------------------------------------------------
# GET /incidents/{id}/approvals
# -----------------------------------------------------------------------
@router.get("/incidents/{incident_id}/approvals")
async def list_approvals(incident_id: str):
    container = await get_approvals_container()

    query = "SELECT * FROM c WHERE c.incident_id = @incident_id"
    parameters = [{"name": "@incident_id", "value": incident_id}]

    results = []
    async for doc in container.query_items(query=query, parameters=parameters, partition_key=incident_id):
        results.append({
            "id": doc["id"],
            "incident_id": doc["incident_id"],
            "action": doc.get("action", {}),
            "similar_past_incidents": doc.get("similar_past_incidents", []),
            "requested_at": doc["requested_at"],
            "decided_at": doc.get("decided_at"),
            "decision": doc.get("decision"),
            "note": doc.get("note"),
        })

    return results


# -----------------------------------------------------------------------
# POST /incidents/{id}/approvals/{aid}
# -----------------------------------------------------------------------
@router.post("/incidents/{incident_id}/approvals/{approval_id}")
async def submit_approval(
    incident_id: str,
    approval_id: str,
    decision: ApprovalDecision,
):
    now = datetime.now(timezone.utc)

    # 1. Validate approval exists and is pending
    container = await get_approvals_container()
    logger.info("submit_approval.debug", incident_id=repr(incident_id), approval_id=repr(approval_id))
    try:
        doc = await container.read_item(item=approval_id, partition_key=incident_id)
        logger.info("submit_approval.found_item", doc_id=doc.get("id"))
    except CosmosResourceNotFoundError:
        logger.error("submit_approval.not_found", incident_id=repr(incident_id), approval_id=repr(approval_id))
        raise HTTPException(
            status_code=404,
            detail=f"Approval {approval_id} not found for incident {incident_id}",
        )

    if doc.get("decision") != ApprovalStatus.pending.value:
        raise HTTPException(
            status_code=409,
            detail=f"Approval {approval_id} already decided: {doc.get('decision')}",
        )

    # 2. Update DB — read-modify-upsert
    new_status = ApprovalStatus.approved if decision.approved else ApprovalStatus.rejected

    doc["decision"] = new_status.value
    doc["decided_at"] = now.isoformat()
    doc["note"] = decision.note
    await container.upsert_item(doc)

    # 3. Resume investigation flow asynchronously
    try:
        from orchestrator.manager import resume_investigation
        import asyncio
        asyncio.create_task(resume_investigation(incident_id, decision.approved))
    except Exception as exc:
        logger.error("approval.resume_error", incident_id=incident_id, error=str(exc))

    # 4. Emit event
    event_bus = get_event_bus()
    await event_bus.publish(incident_id, {
        "type": "approval_response",
        "payload": {
            "approval_id": approval_id,
            "incident_id": incident_id,
            "decision": new_status.value,
            "note": decision.note,
        },
    })

    logger.info(
        "approval.submitted",
        incident_id=incident_id,
        approval_id=approval_id,
        decision=new_status.value,
    )

    # 5. Return updated approval
    updated = await container.read_item(item=approval_id, partition_key=incident_id)

    return {
        "id": updated["id"],
        "incident_id": updated["incident_id"],
        "action": updated.get("action", {}),
        "similar_past_incidents": updated.get("similar_past_incidents", []),
        "requested_at": updated["requested_at"],
        "decided_at": updated.get("decided_at"),
        "decision": updated.get("decision"),
        "note": updated.get("note"),
    }
