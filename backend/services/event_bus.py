import json
import uuid
import datetime
import structlog
from typing import AsyncGenerator

from azure.servicebus.aio import ServiceBusClient
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio.management import ServiceBusAdministrationClient
from app.config import get_settings
from db.database import get_incidents_container

logger = structlog.get_logger(__name__)


class EventBus:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventBus, cls).__new__(cls)
        return cls._instance

    async def publish(self, incident_id: str, event: dict):
        """Publish a message to the Service Bus Topic `swarm-events`."""
        settings = get_settings()
        conn_str = settings.AZURE_SERVICEBUS_CONNECTION_STRING
        if not conn_str:
            logger.warning("event_bus.publish_skipped", reason="Azure Service Bus connection string not configured")
            return

        event_type = event.get("type", "unknown")
        logger.info("event_bus.publish", incident_id=incident_id, event_type=event_type)

        try:
            # --- Auto-persist certain dynamic events to the incident timeline ---
            if incident_id and incident_id != "global" and event_type in (
                "agent_status_change", "evidence_node_added", "conflict_detected",
                "consensus_reached", "postmortem_ready"
            ):
                payload = event.get("payload", {})
                tl_event_text = None
                tl_agent = None
                tl_round = payload.get("round_number")
                
                if event_type == "agent_status_change":
                    tl_event_text = f"Status changed to {payload.get('status')}"
                    tl_agent = payload.get("agent_id")
                elif event_type == "evidence_node_added":
                    tl_event_text = f"Discovered new evidence: {payload.get('evidence_type')}"
                    tl_agent = payload.get("agent")
                elif event_type == "conflict_detected":
                    tl_event_text = f"Conflict detected between {payload.get('agent_a')} and {payload.get('agent_b')}"
                    tl_agent = "consensus_engine"
                elif event_type == "consensus_reached":
                    tl_event_text = "Consensus reached successfully"
                    tl_agent = "consensus_engine"
                elif event_type == "postmortem_ready":
                    tl_event_text = "Postmortem report generated"
                    tl_agent = "postmortem_intel"

                if tl_event_text:
                    try:
                        container = await get_incidents_container()
                        doc = await container.read_item(item=incident_id, partition_key=incident_id)
                        
                        entry = {
                            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "event": tl_event_text,
                            "agent": tl_agent,
                            "round_number": tl_round,
                        }
                        
                        # Only append if it's not a duplicate status change to prevent spam
                        timeline = doc.setdefault("timeline", [])
                        if not timeline or timeline[-1].get("event") != tl_event_text or timeline[-1].get("agent") != tl_agent:
                            timeline.append(entry)
                            await container.upsert_item(doc)
                    except Exception as db_err:
                        logger.warning("event_bus.timeline_persist_failed", error=str(db_err))
            # ----------------------------------------------------------------

            async with ServiceBusClient.from_connection_string(conn_str) as client:
                async with client.get_topic_sender(topic_name="swarm-events") as sender:
                    message_data = json.dumps({
                        "incident_id": incident_id,
                        "event": event
                    })
                    message = ServiceBusMessage(message_data)
                    await sender.send_messages(message)
        except Exception as e:
            logger.error("event_bus.publish_failed", incident_id=incident_id, error=str(e))

    async def publish_global(self, event: dict):
        """Publish a message globally to all incident subscribers."""
        await self.publish("global", event)

    async def subscribe(self, incident_id: str) -> AsyncGenerator[dict, None]:
        """Subscribe to events for a specific incident from a dynamic Service Bus subscription.
        
        Yields deserialized event payloads as they arrive.
        """
        settings = get_settings()
        conn_str = settings.AZURE_SERVICEBUS_CONNECTION_STRING
        if not conn_str:
            logger.warning("event_bus.subscribe_skipped", reason="Azure Service Bus connection string not configured")
            return

        topic_name = "swarm-events"
        subscription_name = f"sub-{incident_id}-{uuid.uuid4().hex[:8]}"

        # 1. Create subscription dynamically with a 5 minute idle timeout
        try:
            async with ServiceBusAdministrationClient.from_connection_string(conn_str) as admin_client:
                # Ensure the topic exists first
                try:
                    await admin_client.get_topic(topic_name)
                except Exception:
                    try:
                        await admin_client.create_topic(topic_name)
                    except Exception:
                        pass

                await admin_client.create_subscription(
                    topic_name=topic_name,
                    subscription_name=subscription_name,
                    auto_delete_on_idle=datetime.timedelta(minutes=5)
                )
            logger.info("event_bus.subscription_created", subscription=subscription_name, incident_id=incident_id)
        except Exception as e:
            logger.error("event_bus.subscription_creation_failed", incident_id=incident_id, error=str(e))
            return

        # 2. Consume events from the receiver loop
        try:
            async with ServiceBusClient.from_connection_string(conn_str) as client:
                async with client.get_subscription_receiver(
                    topic_name=topic_name,
                    subscription_name=subscription_name
                ) as receiver:
                    async for msg in receiver:
                        try:
                            body = json.loads(str(msg))
                            await receiver.complete_message(msg)

                            msg_incident_id = body.get("incident_id")
                            if msg_incident_id == incident_id or msg_incident_id == "global":
                                yield body.get("event")
                        except Exception as parse_err:
                            logger.error("event_bus.parse_message_failed", error=str(parse_err))
        except Exception as e:
            # Handle cancellation gracefully (e.g. websocket disconnect)
            logger.info("event_bus.receive_loop_terminated", incident_id=incident_id, reason=str(e))
        finally:
            # 3. Clean up the dynamic subscription
            try:
                async with ServiceBusAdministrationClient.from_connection_string(conn_str) as admin_client:
                    await admin_client.delete_subscription(topic_name, subscription_name)
                logger.info("event_bus.subscription_deleted", subscription=subscription_name)
            except Exception as cleanup_err:
                logger.warning("event_bus.subscription_cleanup_failed", subscription=subscription_name, error=str(cleanup_err))


_event_bus = EventBus()

async def init_event_bus():
    pass

def get_event_bus() -> EventBus:
    return _event_bus
