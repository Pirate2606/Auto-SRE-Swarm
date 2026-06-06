import asyncio
import json
import uuid
import structlog
from datetime import datetime, timezone
from typing import List

from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchFieldDataType,
)
from azure.core.credentials import AzureKeyCredential
from app.config import get_settings
from app.models import PastIncident, RecurrenceReport

logger = structlog.get_logger(__name__)


class IncidentMemoryStore:
    def __init__(self):
        self._index_ensured = False

    async def _ensure_index(self):
        """Create the incident-memory index in Azure AI Search if it doesn't exist."""
        if self._index_ensured:
            return

        settings = get_settings()
        if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
            return

        from azure.core.exceptions import ResourceNotFoundError
        try:
            async with SearchIndexClient(
                endpoint=settings.AZURE_SEARCH_ENDPOINT,
                credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY),
            ) as index_client:
                try:
                    await index_client.get_index("incident-memory")
                    self._index_ensured = True
                    return
                except ResourceNotFoundError:
                    pass

                index = SearchIndex(
                    name="incident-memory",
                    fields=[
                        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                        SimpleField(name="incident_id", type=SearchFieldDataType.String),
                        SearchableField(name="title", type=SearchFieldDataType.String),
                        SearchableField(name="root_cause", type=SearchFieldDataType.String),
                        SearchableField(name="resolution", type=SearchFieldDataType.String),
                        SimpleField(name="occurred_at", type=SearchFieldDataType.String),
                        SimpleField(name="metadata", type=SearchFieldDataType.String),
                    ],
                )
                await index_client.create_index(index)
                self._index_ensured = True
                logger.info("memory_store.index_ensured", index_name="incident-memory")
        except Exception as exc:
            logger.error("memory_store.ensure_index_error", error=str(exc))

    async def store_incident(self, incident_id: str, title: str, root_cause: str, resolution: str, metadata: dict = {}) -> None:
        """Upload a resolved incident document to the Azure AI Search index `incident-memory`
        and also persist to Cosmos DB MemoryStore container as a fallback."""
        settings = get_settings()

        # ── Cosmos DB dual-write ──────────────────────────────────────
        try:
            from db.database import get_memory_container
            container = await get_memory_container()
            record_id = incident_id.replace(":", "_").replace("/", "_")
            cosmos_doc = {
                "id": record_id,
                "incident_id": incident_id,
                "title": title,
                "root_cause": root_cause,
                "resolution": resolution,
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "metadata": json.dumps(metadata) if isinstance(metadata, dict) else str(metadata),
            }
            await container.upsert_item(cosmos_doc)
            logger.info("memory_store.cosmos_stored", incident_id=incident_id)
        except Exception as exc:
            logger.error("memory_store.cosmos_store_error", incident_id=incident_id, error=str(exc))

        # ── Azure AI Search write ─────────────────────────────────────
        if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
            logger.warning("memory_store.store_skipped", reason="Azure AI Search credentials not configured")
            return

        await self._ensure_index()

        now = datetime.now(timezone.utc)
        record_id = incident_id.replace(":", "_").replace("/", "_")

        doc = {
            "id": record_id,
            "incident_id": incident_id,
            "title": title,
            "root_cause": root_cause,
            "resolution": resolution,
            "occurred_at": now.isoformat(),
            "metadata": json.dumps(metadata) if isinstance(metadata, dict) else str(metadata),
        }

        try:
            async with SearchClient(
                endpoint=settings.AZURE_SEARCH_ENDPOINT,
                index_name="incident-memory",
                credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY)
            ) as client:
                result = await client.upload_documents(documents=[doc])
                # Check for per-document errors
                for r in result:
                    if not r.succeeded:
                        logger.error("memory_store.upload_doc_error", incident_id=incident_id, error=r.error_message)
                    else:
                        logger.info("memory_store.search_stored", incident_id=incident_id)
        except Exception as exc:
            logger.error("memory_store.store_error", incident_id=incident_id, error=str(exc), error_type=type(exc).__name__)

    async def recall_similar(self, description: str, top_k: int = 3) -> List[PastIncident]:
        """Query Azure AI Search for similar incidents based on the description."""
        settings = get_settings()
        if not settings.AZURE_SEARCH_ENDPOINT or not settings.AZURE_SEARCH_KEY:
            logger.warning("memory_store.recall_skipped", reason="Azure AI Search credentials not configured")
            return []

        await self._ensure_index()

        results = []
        try:
            async with SearchClient(
                endpoint=settings.AZURE_SEARCH_ENDPOINT,
                index_name="incident-memory",
                credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY)
            ) as client:
                # Perform search (using search_text which utilizes keyword & semantic ranking if configured)
                async for result in await client.search(
                    search_text=description,
                    top=top_k
                ):
                    doc = result
                    score = result.get("@search.score", 0.5)

                    occurred_at_str = doc.get("occurred_at")
                    if isinstance(occurred_at_str, str):
                        try:
                            occurred_at = datetime.fromisoformat(occurred_at_str)
                        except ValueError:
                            occurred_at = datetime.now(timezone.utc)
                    else:
                        occurred_at = occurred_at_str or datetime.now(timezone.utc)

                    results.append(PastIncident(
                        id=doc.get("incident_id") or doc.get("id"),
                        title=doc.get("title", ""),
                        root_cause=doc.get("root_cause", ""),
                        resolution=doc.get("resolution", ""),
                        similarity=float(score),
                        occurred_at=occurred_at
                    ))
        except Exception as exc:
            logger.error("memory_store.recall_error", query=description, error=str(exc), error_type=type(exc).__name__)
            return []

        results.sort(key=lambda x: x.similarity, reverse=True)
        
        # Filter out low quality matches (BM25 OR-logic matches on stop words)
        if results:
            top_score = results[0].similarity
            # Require at least a score of 1.0, and must be within 50% of the best match
            results = [r for r in results if r.similarity >= 1.0 and r.similarity >= (top_score * 0.5)]
            
        top_results = results[:top_k]
        
        top_score = top_results[0].similarity if top_results else 0.0
        logger.info("memory_store.recall", query=description[:50], result_count=len(top_results), top_score=round(top_score, 3))
        
        return top_results

    async def detect_recurrence(self, description: str, incident_id: str) -> RecurrenceReport:
        similar = await self.recall_similar(description, top_k=10)
        similar = [inc for inc in similar if inc.id != incident_id]
        
        now = datetime.now(timezone.utc)
        count_30d = 0
        count_90d = 0
        
        for inc in similar:
            inc_date = inc.occurred_at
            if inc_date.tzinfo is None:
                inc_date = inc_date.replace(tzinfo=timezone.utc)
                
            delta = now - inc_date
            if delta.days <= 30:
                count_30d += 1
            if delta.days <= 90:
                count_90d += 1
                
        is_recurring = len(similar) > 0
        
        pattern = None
        if len(similar) >= 2:
            root_causes = [inc.root_cause for inc in similar[:3]]
            pattern = "Common themes: " + " | ".join(root_causes)
            
        return RecurrenceReport(
            is_recurring=is_recurring,
            occurrences_30d=count_30d,
            occurrences_90d=count_90d,
            similar_incidents=similar,
            pattern_description=pattern
        )

    async def get_proven_remediations(self, root_cause: str) -> List[str]:
        similar = await self.recall_similar(root_cause, top_k=5)
        
        resolutions = []
        seen = set()
        for inc in similar:
            res = inc.resolution.strip()
            if res and res not in seen:
                resolutions.append(res)
                seen.add(res)
                
        return resolutions
