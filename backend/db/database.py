"""
Azure Cosmos DB initialisation module.

Provides async helpers to obtain the CosmosClient, database, and
pre-provisioned containers used by the SRE Swarm services.

Containers
----------
* **Incidents**        – partition key ``/id``
* **Evidence**         – partition key ``/incident_id``
* **Approvals**        – partition key ``/incident_id``
* **ConsensusResults** – partition key ``/incident_id``
* **Postmortems**      – partition key ``/incident_id``
* **MemoryStore**      – partition key ``/incident_id``
"""

import structlog
from azure.cosmos.aio import CosmosClient
from azure.cosmos import PartitionKey
from app.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

# ── Module-level singletons (lazily initialised) ──────────────────────
_cosmos_client: CosmosClient | None = None
_database = None
_incidents_container = None
_evidence_container = None
_approvals_container = None
_consensus_container = None
_postmortems_container = None
_memory_container = None

DATABASE_NAME = "SreSwarmDB"


def _get_cosmos_client() -> CosmosClient:
    """Return a module-level CosmosClient (created once)."""
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosClient(
            url=settings.AZURE_COSMOS_ENDPOINT,
            credential=settings.AZURE_COSMOS_KEY,
        )
    return _cosmos_client


async def init_db() -> None:
    """
    Initialise the Cosmos DB database and containers.

    Creates the database ``SreSwarmDB`` and five containers if they do
    not already exist:

    * **Incidents**        – partition key ``/id``
    * **Evidence**         – partition key ``/incident_id``
    * **Approvals**        – partition key ``/incident_id``
    * **ConsensusResults** – partition key ``/incident_id``
    * **Postmortems**      – partition key ``/incident_id``
    * **MemoryStore**      – partition key ``/incident_id``
    """
    global _database, _incidents_container, _evidence_container
    global _approvals_container, _consensus_container, _postmortems_container
    global _memory_container

    logger.info("cosmos.init", database=DATABASE_NAME)
    client = _get_cosmos_client()

    _database = await client.create_database_if_not_exists(
        id=DATABASE_NAME, 
        offer_throughput=400
    )

    _incidents_container = await _database.create_container_if_not_exists(
        id="Incidents",
        partition_key=PartitionKey(path="/id"),
    )

    _evidence_container = await _database.create_container_if_not_exists(
        id="Evidence",
        partition_key=PartitionKey(path="/incident_id"),
    )

    _approvals_container = await _database.create_container_if_not_exists(
        id="Approvals",
        partition_key=PartitionKey(path="/incident_id"),
    )

    _consensus_container = await _database.create_container_if_not_exists(
        id="ConsensusResults",
        partition_key=PartitionKey(path="/incident_id"),
    )

    _postmortems_container = await _database.create_container_if_not_exists(
        id="Postmortems",
        partition_key=PartitionKey(path="/incident_id"),
    )

    _memory_container = await _database.create_container_if_not_exists(
        id="MemoryStore",
        partition_key=PartitionKey(path="/incident_id"),
    )

    logger.info("cosmos.init.complete", database=DATABASE_NAME)


async def get_database():
    """Return the initialised DatabaseProxy (call ``init_db`` first)."""
    if _database is None:
        await init_db()
    return _database


async def get_incidents_container():
    """Return the *Incidents* container proxy."""
    if _incidents_container is None:
        await init_db()
    return _incidents_container


async def get_evidence_container():
    """Return the *Evidence* container proxy."""
    if _evidence_container is None:
        await init_db()
    return _evidence_container


async def get_approvals_container():
    """Return the *Approvals* container proxy."""
    if _approvals_container is None:
        await init_db()
    return _approvals_container


async def get_consensus_container():
    """Return the *ConsensusResults* container proxy."""
    if _consensus_container is None:
        await init_db()
    return _consensus_container


async def get_postmortems_container():
    """Return the *Postmortems* container proxy."""
    if _postmortems_container is None:
        await init_db()
    return _postmortems_container


async def get_memory_container():
    """Return the *MemoryStore* container proxy."""
    if _memory_container is None:
        await init_db()
    return _memory_container


async def close_db() -> None:
    """Close the underlying Cosmos client (call on app shutdown)."""
    global _cosmos_client, _database, _incidents_container, _evidence_container
    global _approvals_container, _consensus_container, _postmortems_container
    global _memory_container
    if _cosmos_client is not None:
        await _cosmos_client.close()
        _cosmos_client = None
        _database = None
        _incidents_container = None
        _evidence_container = None
        _approvals_container = None
        _consensus_container = None
        _postmortems_container = None
        _memory_container = None
        logger.info("cosmos.closed")
