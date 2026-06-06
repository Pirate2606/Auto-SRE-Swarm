import asyncio
import json
from datetime import datetime, timezone

import structlog
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.deps import get_event_bus, get_evidence_store
from app.models import ApprovalDecision
from api.routes_approval import submit_approval
from db.database import get_incidents_container, get_postmortems_container, get_consensus_container

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api")

# Simple connection manager (incident_id -> set of WebSockets)
_active_connections: dict[str, set[WebSocket]] = {}


async def _get_incident_state_sync(incident_id: str) -> dict | None:
    """Check if incident exists, and fetch state/timeline for sync."""
    container = await get_incidents_container()
    try:
        doc = await container.read_item(item=incident_id, partition_key=incident_id)
    except CosmosResourceNotFoundError:
        return None

    timeline = doc.get("timeline", [])
    agent_findings = doc.get("agent_findings", [])
    
    store = get_evidence_store()
    try:
        nodes = await store.get_incident_graph(incident_id)
        evidence_nodes = [n.model_dump(mode="json") for n in nodes]
    except Exception as exc:
        logger.warning("ws.sync_fetch_evidence_error", incident_id=incident_id, error=str(exc))
        evidence_nodes = []

    pm_container = await get_postmortems_container()
    postmortem = None
    try:
        query = "SELECT * FROM c WHERE c.incident_id = @incident_id"
        parameters = [{"name": "@incident_id", "value": incident_id}]
        async for pm in pm_container.query_items(query=query, parameters=parameters, partition_key=incident_id):
            postmortem = pm
            break
    except Exception as exc:
        logger.warning("ws.sync_fetch_postmortem_error", incident_id=incident_id, error=str(exc))

    cons_container = await get_consensus_container()
    consensus = None
    try:
        query = "SELECT * FROM c WHERE c.incident_id = @incident_id ORDER BY c.round_number DESC"
        parameters = [{"name": "@incident_id", "value": incident_id}]
        async for cons in cons_container.query_items(query=query, parameters=parameters, partition_key=incident_id):
            consensus = cons
            break
    except Exception as exc:
        logger.warning("ws.sync_fetch_consensus_error", incident_id=incident_id, error=str(exc))

    return {
        "incident": doc,
        "timeline": timeline,
        "agent_findings": agent_findings,
        "evidence_nodes": evidence_nodes,
        "postmortem": postmortem,
        "consensus": consensus,
        "conflicts": doc.get("conflicts", []),
    }


def _envelope(event_name: str, incident_id: str, payload: dict) -> dict:
    """Build the required WebSocket event envelope."""
    return {
        "event": event_name,
        "incident_id": incident_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "round": 0,  # We can set default round here; the client ignores if not applicable
        "payload": payload,
    }


@router.websocket("/ws/incidents/{incident_id}")
async def websocket_incident(websocket: WebSocket, incident_id: str):
    # 1. Accept connection
    await websocket.accept()

    # Connection limit check
    settings = get_settings()
    max_conns = getattr(settings, "MAX_WS_CONNECTIONS_PER_INCIDENT", 50)
    conns = _active_connections.setdefault(incident_id, set())
    
    if len(conns) >= max_conns:
        err = _envelope("error", incident_id, {
            "code": "TOO_MANY_CONNECTIONS", 
            "message": f"Max {max_conns} connections reached",
            "agent": None
        })
        await websocket.send_json(err)
        await websocket.close(code=1013)
        return

    # 2. Validate incident exists
    state = await _get_incident_state_sync(incident_id)
    if not state:
        err = _envelope("error", incident_id, {
            "code": "NOT_FOUND",
            "message": f"Incident {incident_id} not found",
            "agent": None
        })
        await websocket.send_json(err)
        await websocket.close(code=4004)
        return

    _active_connections[incident_id].add(websocket)

    # 3. Subscribe to EventBus
    event_bus = get_event_bus()

    consume_task = None
    ping_task = None

    try:
        # 4. Send "connected" handshake
        await websocket.send_json(_envelope("connected", incident_id, {}))

        # Reconnection sync event
        await websocket.send_json(_envelope("incident_state_sync", incident_id, state))

        last_pong = datetime.now(timezone.utc)

        # Ping/Pong Heartbeat Task
        async def _ping_loop():
            nonlocal last_pong
            while True:
                await asyncio.sleep(30)
                try:
                    await websocket.send_json(_envelope("ping", incident_id, {}))
                except Exception:
                    break

                # Wait 10s for pong
                await asyncio.sleep(10)
                if (datetime.now(timezone.utc) - last_pong).total_seconds() > 15:
                    logger.warning("ws.pong_timeout", incident_id=incident_id)
                    try:
                        await websocket.close(code=1008)
                    except Exception:
                        pass
                    break

        ping_task = asyncio.create_task(_ping_loop())

        # Consume EventBus Task
        async def _consume_loop():
            async for msg in event_bus.subscribe(incident_id):
                event_type = msg.get("type", "unknown")
                payload = msg.get("payload", {})
                try:
                    await websocket.send_json(_envelope(event_type, incident_id, payload))
                except Exception:
                    break

        consume_task = asyncio.create_task(_consume_loop())

        # Main Receive Loop
        while True:
            data = await websocket.receive_json()
            event = data.get("event")
            
            if event == "pong":
                last_pong = datetime.now(timezone.utc)
                
            elif event == "approval_response":
                payload = data.get("payload", {})
                action_id = payload.get("action_id")
                approved = payload.get("approved", False)
                note = payload.get("note")
                
                decision = ApprovalDecision(approved=approved, note=note)
                try:
                    # 6. Internally call submit_approval REST endpoint logic
                    await submit_approval(incident_id, action_id, decision)
                except Exception as exc:
                    logger.error("ws.approval_handler_error", incident_id=incident_id, error=str(exc))
                    await websocket.send_json(_envelope("error", incident_id, {
                        "code": "APPROVAL_ERROR",
                        "message": str(exc),
                        "agent": None
                    }))

    except WebSocketDisconnect:
        logger.info("ws.disconnected", incident_id=incident_id)
    except Exception as exc:
        logger.error("ws.error", incident_id=incident_id, error=str(exc))
        try:
            await websocket.send_json(_envelope("error", incident_id, {
                "code": "INTERNAL_ERROR",
                "message": "WebSocket server error",
                "agent": None
            }))
        except Exception:
            pass
    finally:
        # 7. Disconnect -> dynamic subscription is automatically cleaned up when generator exits
        
        if websocket in _active_connections.get(incident_id, set()):
            _active_connections[incident_id].remove(websocket)
            if not _active_connections[incident_id]:
                del _active_connections[incident_id]
                
        if ping_task:
            ping_task.cancel()
        if consume_task:
            consume_task.cancel()
            
        try:
            await websocket.close()
        except Exception:
            pass
