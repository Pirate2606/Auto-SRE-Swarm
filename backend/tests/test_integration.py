import pytest
import asyncio
from datetime import datetime, timezone
import json
import uuid

from app.models import (
    Incident,
    IncidentStatus,
    AgentName,
    AgentFindingLLM,
    ChallengeResultLLM,
    ChallengeVerdict,
    RiskAssessmentLLM,
    RiskLevel,
    PostmortemLLM,
    Severity,
    PastIncident,
)
from app.deps import get_llm, get_evidence_store, get_memory_store
import db.database
from orchestrator.manager import start_investigation_loop, resume_investigation


class MockLLM:
    """Deterministic Mock LLM for integration tests."""
    
    def __init__(self):
        self.mode = "happy_path"
        self.call_count = 0
        
    async def complete(self, system_prompt: str, user_message: str, response_schema: type, incident_id: str, **kwargs):
        self.call_count += 1
        
        # AgentFindingLLM responses
        if response_schema == AgentFindingLLM:
            if "Log Forensics" in system_prompt:
                if self.mode == "conflict":
                    return AgentFindingLLM(
                        root_cause_hypothesis="traffic spike",
                        summary="high traffic volume",
                        supporting_evidence=["log a"],
                        confidence=0.8,
                        evidence_type="log",
                        raw_findings={}
                    )
                if self.mode == "low_confidence":
                    return AgentFindingLLM(
                        root_cause_hypothesis="unknown",
                        summary="uncertain log indicators",
                        supporting_evidence=["log a"],
                        confidence=0.4,
                        evidence_type="log",
                        raw_findings={}
                    )
                return AgentFindingLLM(
                    root_cause_hypothesis="OOM hypothesis",
                    summary="OOM signature seen in logs",
                    supporting_evidence=["OOM log"],
                    confidence=0.8,
                    evidence_type="log",
                    raw_findings={}
                )
                
            if "Telemetry Intelligence" in system_prompt:
                if self.mode == "conflict":
                    return AgentFindingLLM(
                        root_cause_hypothesis="memory leak",
                        summary="gradual memory expansion",
                        supporting_evidence=["metric b"],
                        confidence=0.85,
                        evidence_type="metric",
                        raw_findings={}
                    )
                if self.mode == "low_confidence":
                    return AgentFindingLLM(
                        root_cause_hypothesis="unknown",
                        summary="fluctuating resource levels",
                        supporting_evidence=["metric b"],
                        confidence=0.4,
                        evidence_type="metric",
                        raw_findings={}
                    )
                return AgentFindingLLM(
                    root_cause_hypothesis="memory saturation hypothesis",
                    summary="memory consumption reached limit",
                    supporting_evidence=["memory metric"],
                    confidence=0.85,
                    evidence_type="metric",
                    raw_findings={}
                )
                
            if "Deployment Intelligence" in system_prompt:
                if self.mode == "low_confidence":
                    return AgentFindingLLM(
                        root_cause_hypothesis="unknown",
                        summary="no clear deployment change",
                        supporting_evidence=["git log"],
                        confidence=0.4,
                        evidence_type="git",
                        raw_findings={}
                    )
                return AgentFindingLLM(
                    root_cause_hypothesis="no deployment correlation",
                    summary="no deploys within critical window",
                    supporting_evidence=["git log"],
                    confidence=0.9,
                    evidence_type="git",
                    raw_findings={}
                )
        
        # ChallengeResultLLM response
        if response_schema == ChallengeResultLLM:
            return ChallengeResultLLM(verdict=ChallengeVerdict.agree, reasoning="Mocked agree", confidence_adjustment=0.1)
            
        # RiskAssessmentLLM response
        if response_schema == RiskAssessmentLLM:
            if self.mode == "high_risk":
                return RiskAssessmentLLM(risk_level=RiskLevel.high, estimated_impact="High impact", rollback_plan="Revert", justification="Mocked high risk")
            return RiskAssessmentLLM(risk_level=RiskLevel.low, estimated_impact="Low impact", rollback_plan="Revert", justification="Mocked low risk")
            
        # PostmortemLLM response
        if response_schema == PostmortemLLM:
            return PostmortemLLM(
                executive_summary="Mocked Summary",
                root_cause="Mocked Cause",
                contributing_factors=["Factor A"],
                remediation_actions=[{"action": "Fix it", "priority": "high", "owner": "SRE", "estimated_effort": "1h"}],
                prevention_recommendations=["Prevent it"]
            )
            
        # Fallback for ActionsLLM
        if hasattr(response_schema, "model_fields") and "actions" in response_schema.model_fields:
            return response_schema(actions=[{"title": "Restart pods", "description": "Safe restart"}])
            
        # Default mock
        return response_schema()

    async def health_check(self):
        return True


# ── Mocks for Cosmos DB and Azure Search ──────────────────────────────

class MockCosmosContainer:
    def __init__(self, container_name: str):
        self.name = container_name
        self.items = {}

    async def upsert_item(self, doc: dict):
        self.items[doc["id"]] = doc
        return doc

    async def read_item(self, item: str, partition_key: str):
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        if item in self.items:
            return self.items[item]
        raise CosmosResourceNotFoundError(message=f"Item {item} not found")

    def query_items(self, query: str = None, parameters: list = None, partition_key: str = None, enable_cross_partition_query: bool = False):
        filtered_items = list(self.items.values())
        if parameters:
            param_map = {p["name"]: p["value"] for p in parameters}
            for param_name, param_val in param_map.items():
                field_name = param_name.replace("@", "")
                filtered_items = [
                    item for item in filtered_items
                    if item.get(field_name) == param_val or item.get("id") == param_val
                ]
        
        class AsyncListGenerator:
            def __init__(self, data):
                self.data = data
                self.index = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self.index < len(self.data):
                    val = self.data[self.index]
                    self.index += 1
                    return val
                raise StopAsyncIteration
        
        return AsyncListGenerator(filtered_items)


_mock_containers = {
    "Incidents": MockCosmosContainer("Incidents"),
    "Evidence": MockCosmosContainer("Evidence"),
    "Approvals": MockCosmosContainer("Approvals"),
    "ConsensusResults": MockCosmosContainer("ConsensusResults"),
    "Postmortems": MockCosmosContainer("Postmortems"),
    "MemoryStore": MockCosmosContainer("MemoryStore"),
}

_mock_search_items = {}

_mock_service_bus_subscribers = {}

class MockServiceBusMessage:
    def __init__(self, body):
        self.body = body
    def __str__(self):
        if isinstance(self.body, bytes):
            return self.body.decode("utf-8")
        return str(self.body)

class MockMessage:
    def __init__(self, body):
        self.body = body
    def __str__(self):
        return self.body

class MockReceiver:
    def __init__(self, sub_name):
        self.sub_name = sub_name
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    def __aiter__(self):
        return self
    async def __anext__(self):
        q = _mock_service_bus_subscribers.get(self.sub_name)
        if q is None:
            raise StopAsyncIteration
        msg = await q.get()
        return msg
    async def complete_message(self, message):
        pass

class MockSender:
    def __init__(self, topic_name):
        self.topic_name = topic_name
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    async def send_messages(self, message):
        body = str(message)
        for q in list(_mock_service_bus_subscribers.values()):
            await q.put(MockMessage(body))

class MockServiceBusClient:
    def __init__(self, conn_str=None):
        self.conn_str = conn_str
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    def get_topic_sender(self, topic_name):
        return MockSender(topic_name)
    def get_subscription_receiver(self, topic_name, subscription_name):
        return MockReceiver(subscription_name)
    @classmethod
    def from_connection_string(cls, conn_str, **kwargs):
        return cls(conn_str)

class MockServiceBusAdministrationClient:
    def __init__(self, conn_str=None):
        self.conn_str = conn_str
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    async def get_topic(self, topic_name):
        return True
    async def create_topic(self, topic_name):
        return True
    async def create_subscription(self, topic_name, subscription_name, **kwargs):
        if subscription_name not in _mock_service_bus_subscribers:
            _mock_service_bus_subscribers[subscription_name] = asyncio.Queue()
        return True
    async def delete_subscription(self, topic_name, subscription_name):
        if subscription_name in _mock_service_bus_subscribers:
            del _mock_service_bus_subscribers[subscription_name]
        return True
    @classmethod
    def from_connection_string(cls, conn_str, **kwargs):
        return cls(conn_str)

class MockSearchClient:
    def __init__(self, endpoint=None, index_name=None, credential=None):
        self.endpoint = endpoint
        self.index_name = index_name

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def upload_documents(self, documents: list):
        for doc in documents:
            _mock_search_items[doc["id"]] = doc
        return documents

    async def search(self, search_text: str, top: int = 3):
        filtered = list(_mock_search_items.values())
        class AsyncSearchGenerator:
            def __init__(self, data):
                self.data = data
                self.index = 0
            def __aiter__(self):
                return self
            async def __anext__(self):
                if self.index < len(self.data):
                    val = self.data[self.index].copy()
                    val["@search.score"] = 0.99
                    self.index += 1
                    return val
                raise StopAsyncIteration
        return AsyncSearchGenerator(filtered)


@pytest.fixture(autouse=True)
def mock_azure_services(monkeypatch):
    # Mock database.py
    import db.database
    async def mock_init(): pass
    async def mock_close(): pass
    async def mock_get_incidents(): return _mock_containers["Incidents"]
    async def mock_get_evidence(): return _mock_containers["Evidence"]
    async def mock_get_approvals(): return _mock_containers["Approvals"]
    async def mock_get_consensus(): return _mock_containers["ConsensusResults"]
    async def mock_get_postmortems(): return _mock_containers["Postmortems"]
    async def mock_get_memory(): return _mock_containers["MemoryStore"]

    monkeypatch.setattr(db.database, "init_db", mock_init)
    monkeypatch.setattr(db.database, "get_incidents_container", mock_get_incidents)
    monkeypatch.setattr(db.database, "get_evidence_container", mock_get_evidence)
    monkeypatch.setattr(db.database, "get_approvals_container", mock_get_approvals)
    monkeypatch.setattr(db.database, "get_consensus_container", mock_get_consensus)
    monkeypatch.setattr(db.database, "get_postmortems_container", mock_get_postmortems)
    monkeypatch.setattr(db.database, "get_memory_container", mock_get_memory)
    monkeypatch.setattr(db.database, "close_db", mock_close)
    # Set singletons directly to mock containers to override already imported functions in other modules
    monkeypatch.setattr(db.database, "_incidents_container", _mock_containers["Incidents"])
    monkeypatch.setattr(db.database, "_evidence_container", _mock_containers["Evidence"])
    monkeypatch.setattr(db.database, "_approvals_container", _mock_containers["Approvals"])
    monkeypatch.setattr(db.database, "_consensus_container", _mock_containers["ConsensusResults"])
    monkeypatch.setattr(db.database, "_postmortems_container", _mock_containers["Postmortems"])
    monkeypatch.setattr(db.database, "_memory_container", _mock_containers["MemoryStore"])

    # Mock SearchClient in services.memory_store
    import services.memory_store
    monkeypatch.setattr(services.memory_store, "SearchClient", MockSearchClient)
    
    # Mock settings in services.memory_store to have dummy search credentials
    original_get_settings = services.memory_store.get_settings
    def mock_get_settings_memory():
        settings = original_get_settings()
        settings.AZURE_SEARCH_ENDPOINT = "https://mock-search.search.windows.net"
        settings.AZURE_SEARCH_KEY = "mock-key"
        return settings
    monkeypatch.setattr(services.memory_store, "get_settings", mock_get_settings_memory)

    # Set app.deps singletons
    import app.deps
    from services.evidence_store import EvidenceStore
    from services.memory_store import IncidentMemoryStore
    monkeypatch.setattr(app.deps, "_evidence_store", EvidenceStore())
    monkeypatch.setattr(app.deps, "_memory_store", IncidentMemoryStore())

    # Mock Service Bus in services.event_bus
    import services.event_bus
    monkeypatch.setattr(services.event_bus, "ServiceBusClient", MockServiceBusClient)
    monkeypatch.setattr(services.event_bus, "ServiceBusMessage", MockServiceBusMessage)
    monkeypatch.setattr(services.event_bus, "ServiceBusAdministrationClient", MockServiceBusAdministrationClient)
    
    # Mock settings in services.event_bus to have a dummy connection string
    original_get_settings_eb = services.event_bus.get_settings
    def mock_get_settings_event_bus():
        settings = original_get_settings_eb()
        settings.AZURE_SERVICEBUS_CONNECTION_STRING = "Endpoint=sb://mock-sb.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=mock-key"
        return settings
    monkeypatch.setattr(services.event_bus, "get_settings", mock_get_settings_event_bus)

    yield
    # Clear items after each test
    for container in _mock_containers.values():
        container.items.clear()
    _mock_search_items.clear()
    _mock_service_bus_subscribers.clear()

@pytest.fixture
def mock_llm(monkeypatch):
    mock = MockLLM()
    import app.deps
    monkeypatch.setattr(app.deps, "_llm", mock)
    monkeypatch.setattr(app.deps, "get_llm", lambda: mock)
    return mock
async def _setup_incident_in_db(incident_id: str, severity: str = Severity.P3.value, description: str = "System is slow") -> dict:
    doc = {
        "id": incident_id,
        "title": "Test Incident",
        "description": description,
        "severity": severity,
        "source": "alertmanager",
        "metadata": {},
        "status": IncidentStatus.investigating.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "investigation_round": 1,
        "consensus_confidence": None,
        "agent_statuses": {},
        "timeline": [],
        "agent_findings": [],
        "challenge_results": [],
    }
    container = await db.database.get_incidents_container()
    await container.upsert_item(doc)
    return doc

# 1. Full workflow: happy path
@pytest.mark.asyncio
async def test_full_workflow_happy_path(mock_llm):
    mock_llm.mode = "happy_path"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    final_doc = await inc_container.read_item(incident_id, incident_id)
    
    assert final_doc["status"] == IncidentStatus.resolved.value
    
    postmortems_container = await db.database.get_postmortems_container()
    postmortem = await postmortems_container.read_item(incident_id, incident_id)
    assert postmortem is not None
    assert final_doc["consensus_confidence"] >= 0.7
    assert len(final_doc.get("conflicts", [])) == 0

# 2. Conflict detection and challenge round
@pytest.mark.asyncio
async def test_conflict_triggers_challenge_round(mock_llm):
    mock_llm.mode = "conflict"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert len(final_doc.get("challenge_results", [])) > 0

# 3. Reinvestigation loop
@pytest.mark.asyncio
async def test_low_confidence_triggers_reinvestigation(mock_llm):
    mock_llm.mode = "low_confidence"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert final_doc["investigation_round"] == 3

# 4. Human approval flow
@pytest.mark.asyncio
async def test_high_risk_action_requires_approval(mock_llm):
    mock_llm.mode = "high_risk"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    paused_doc = await inc_container.read_item(incident_id, incident_id)
    assert paused_doc["status"] == IncidentStatus.awaiting_approval.value
    
    # Resume workflow with approval
    await resume_investigation(incident_id, approved=True)
    
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert final_doc["status"] == IncidentStatus.resolved.value

# 5. Rejection flow
@pytest.mark.asyncio
async def test_rejected_action_rerouts_commander(mock_llm):
    mock_llm.mode = "high_risk"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    paused_doc = await inc_container.read_item(incident_id, incident_id)
    assert paused_doc["status"] == IncidentStatus.awaiting_approval.value
    
    await resume_investigation(incident_id, approved=False)
    
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert final_doc["status"] == IncidentStatus.investigating.value
    assert final_doc["investigation_round"] == 2

# 6. Memory store recall
@pytest.mark.asyncio
async def test_memory_enriches_investigation(mock_llm):
    memory = get_memory_store()
    await memory.store_incident("inc-past", "DB Slow", "Missing index", "Added index")
    
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id, description="DB is extremely slow")
    
    await start_investigation_loop(incident_id, "DB is extremely slow")
    
    inc_container = await db.database.get_incidents_container()
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert len(final_doc.get("similar_past_incidents", [])) > 0

# 7. WebSocket event ordering
@pytest.mark.asyncio
async def test_websocket_event_order(mock_llm):
    mock_llm.mode = "happy_path"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)

    received_json_messages = []
    sent_pong = False

    class FakeWebSocket:
        def __init__(self):
            self.closed = False
            self.close_code = None
        async def accept(self):
            pass
        async def send_json(self, data):
            received_json_messages.append(data)
        async def receive_json(self):
            nonlocal sent_pong
            if not sent_pong:
                sent_pong = True
                return {"event": "pong"}
            # Block indefinitely; task cancellation will terminate it
            await asyncio.sleep(3600)
        async def close(self, code=1000):
            self.closed = True
            self.close_code = code

    from api.routes_ws import websocket_incident
    
    ws = FakeWebSocket()
    # Run the websocket loop in the background
    ws_task = asyncio.create_task(websocket_incident(ws, incident_id))
    
    # Wait for the ws to connect and receive initial handshake messages
    await asyncio.sleep(0.1)
    
    # Trigger the investigation loop which publishes events
    await start_investigation_loop(incident_id, "System is slow")
    
    # Wait for the WS loop to process all published events and terminate on disconnect
    await asyncio.sleep(0.5)
    
    if not ws_task.done():
        ws_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

    # Yield control to allow background cleanup tasks to complete while mocks are active
    await asyncio.sleep(0.2)

    # Verify that the websocket received the expected flow of events
    event_names = [m["event"] for m in received_json_messages]
    assert "connected" in event_names
    assert "incident_state_sync" in event_names
    assert "timeline_updated" in event_names

# 8. Evidence DAG integrity
@pytest.mark.asyncio
async def test_evidence_dag_has_correct_structure(mock_llm):
    mock_llm.mode = "happy_path"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    evidence_store = get_evidence_store()
    nodes = await evidence_store.get_incident_graph(incident_id)
    assert len(nodes) >= 3

# 9. P1 fast-path override
@pytest.mark.asyncio
async def test_p1_severity_can_proceed_at_round_2_despite_low_confidence(mock_llm):
    mock_llm.mode = "low_confidence"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id, severity=Severity.P1.value)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert final_doc["status"] == IncidentStatus.resolved.value

# 10. Max rounds safeguard
@pytest.mark.asyncio
async def test_workflow_never_exceeds_max_rounds(mock_llm):
    mock_llm.mode = "low_confidence"
    incident_id = f"inc-{uuid.uuid4().hex[:8]}"
    await _setup_incident_in_db(incident_id)
    
    await start_investigation_loop(incident_id, "System is slow")
    
    inc_container = await db.database.get_incidents_container()
    final_doc = await inc_container.read_item(incident_id, incident_id)
    assert final_doc["investigation_round"] <= 3
