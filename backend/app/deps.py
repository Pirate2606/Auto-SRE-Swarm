from functools import lru_cache
from services.evidence_store import EvidenceStore
from services.memory_store import IncidentMemoryStore
from services.event_bus import EventBus, get_event_bus
from services.llm import AzureOpenAIClient

_evidence_store: EvidenceStore | None = None
_memory_store: IncidentMemoryStore | None = None
_llm: AzureOpenAIClient | None = None


def get_evidence_store() -> EvidenceStore:
    global _evidence_store
    if _evidence_store is None:
        _evidence_store = EvidenceStore()
    return _evidence_store


def get_memory_store() -> IncidentMemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = IncidentMemoryStore()
    return _memory_store


def get_dep_event_bus() -> EventBus:
    return get_event_bus()


def get_llm() -> AzureOpenAIClient:
    global _llm
    if _llm is None:
        _llm = AzureOpenAIClient()
    return _llm
