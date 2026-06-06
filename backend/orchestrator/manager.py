import asyncio
import structlog
from datetime import datetime, timezone
import uuid

import autogen
from app.config import get_settings
from app.models import (
    AgentName,
    AgentStatus,
    ApprovalStatus,
    IncidentStatus,
    TimelineEntry,
    ConsensusResult,
    EvidenceNode,
    AgentFinding,
    ProposedAction,
    Hypothesis,
    Conflict,
    Incident,
    PastIncident,
)
from app.deps import (
    get_llm,
    get_evidence_store,
    get_dep_event_bus,
    get_memory_store,
)
from db.database import (
    get_incidents_container,
    get_consensus_container,
    get_approvals_container,
    get_postmortems_container,
)
from agents.log_forensics import LogForensicsAgent
from agents.telemetry_intel import TelemetryIntelAgent
from agents.deployment_intel import DeploymentIntelAgent
from agents.consensus_engine import ConsensusEngine
from agents.commander import IncidentCommander
from agents.safety_validator import SafetyValidator
from agents.postmortem_intel import PostmortemIntelAgent
from agents.base import SwarmContext

logger = structlog.get_logger(__name__)


# ── AutoGen agent wrappers ────────────────────────────────────────────
# These wrap the domain-specific engines as AutoGen ConversableAgents so
# they participate in the multi-agent conversation framework.

class ConsensusEngineAgent(autogen.ConversableAgent):
    """AutoGen Agent wrapping the Consensus Engine."""
    def __init__(self, consensus_engine: ConsensusEngine):
        super().__init__(
            name="consensus_engine",
            system_message=(
                "You are the Consensus Engine Agent in the SRE swarm.\n"
                "Your role is to fuse findings from all investigation agents and identify conflicts."
            ),
            llm_config=None,
            human_input_mode="NEVER",
        )
        self.consensus_engine = consensus_engine


class IncidentCommanderAgent(autogen.ConversableAgent):
    """AutoGen Agent wrapping the Incident Commander."""
    def __init__(self, llm_config):
        super().__init__(
            name="commander",
            system_message=(
                "You are the Incident Commander Agent in the SRE swarm.\n"
                "You act as the primary Planner/Orchestrator deciding who speaks next "
                "and managing the investigation lifecycle."
            ),
            llm_config=llm_config,
            human_input_mode="NEVER",
        )


async def start_investigation(incident_id: str, context: str):
    """
    Exposed entry point to initiate incident investigation.
    Runs asynchronously in the background.
    """
    asyncio.create_task(start_investigation_loop(incident_id, context))


async def start_investigation_loop(incident_id: str, context: str):
    """
    Main investigation loop using AutoGen agents.

    Architecture
    ────────────
    Phase 1 – Parallel investigation:
        Three AutoGen retriever agents (log_forensics, telemetry_intel,
        deployment_intel) run their `investigate()` method in parallel via
        asyncio.gather().  AutoGen's GroupChat enforces sequential turns,
        so we dispatch the agents directly to achieve true parallelism.

    Phase 2 – Consensus (AutoGen two-party chat):
        The Commander AutoGen agent initiates a chat with the
        ConsensusEngine AutoGen agent.  The ConsensusEngine's registered
        reply handler runs the probabilistic evidence fusion pipeline.

    Phase 3 – Safety validation & Postmortem:
        Direct invocations with status events emitted to the EventBus.
    """
    logger.info("investigation.start_loop", incident_id=incident_id)

    # 1. Retrieve the incident from Cosmos DB
    inc_container = await get_incidents_container()
    try:
        incident_doc = await inc_container.read_item(item=incident_id, partition_key=incident_id)
    except Exception as e:
        logger.error("investigation.not_found", incident_id=incident_id, error=str(e))
        return

    # 2. Update status and initial fields
    incident_doc["status"] = IncidentStatus.investigating.value
    incident_doc["investigation_round"] = 1
    incident_doc["timeline"] = incident_doc.get("timeline", [])
    incident_doc["agent_findings"] = []
    incident_doc["agent_statuses"] = incident_doc.get("agent_statuses", {})
    await inc_container.upsert_item(incident_doc)

    event_bus = get_dep_event_bus()

    async def add_timeline_event(event_text: str, agent_name: AgentName | None = None, round_num: int | None = None):
        entry = TimelineEntry(
            timestamp=datetime.now(timezone.utc),
            event=event_text,
            agent=agent_name,
            round_number=round_num,
        )
        doc = await inc_container.read_item(item=incident_id, partition_key=incident_id)
        doc.setdefault("timeline", []).append(entry.model_dump(mode="json"))
        await inc_container.upsert_item(doc)
        incident_doc["timeline"] = doc["timeline"]
        
        await event_bus.publish(incident_id, {
            "type": "timeline_updated",
            "payload": entry.model_dump(mode="json"),
        })

    await add_timeline_event("Swarm investigation initiated by Commander", AgentName.commander, 1)

    # Emit commander investigating status
    await event_bus.publish(incident_id, {
        "type": "agent_status_change",
        "payload": {"agent_id": "commander", "status": "investigating"},
    })

    # Instantiate services
    llm = get_llm()
    evidence_store = get_evidence_store()
    memory_store = get_memory_store()
    
    # 3. Instantiate AutoGen specialist agents
    log_forensics = LogForensicsAgent(llm, evidence_store, event_bus)
    telemetry_intel = TelemetryIntelAgent(llm, evidence_store, event_bus)
    deployment_intel = DeploymentIntelAgent(llm, evidence_store, event_bus)
    consensus_engine = ConsensusEngine(llm)
    commander_logic = IncidentCommander(llm, evidence_store, memory_store)
    safety_validator = SafetyValidator(llm)
    postmortem_agent = PostmortemIntelAgent(llm, evidence_store, event_bus, memory_store)

    # AutoGen wrappers for the consensus phase
    consensus_agent = ConsensusEngineAgent(consensus_engine)

    settings = get_settings()
    config = {
        "model": settings.AZURE_OPENAI_DEPLOYMENT,
        "api_key": settings.AZURE_OPENAI_API_KEY,
    }
    if "/v1" in settings.AZURE_OPENAI_ENDPOINT:
        config["base_url"] = settings.AZURE_OPENAI_ENDPOINT
    else:
        config["base_url"] = settings.AZURE_OPENAI_ENDPOINT
        config["api_type"] = "azure"
        config["api_version"] = settings.AZURE_OPENAI_API_VERSION

    llm_config = {
        "config_list": [config],
        "temperature": 0.2,
        "cache_seed": None,
    }

    commander_agent = IncidentCommanderAgent(llm_config)

    # Memory recall (first round only)
    similar_past = []
    try:
        similar_past = await memory_store.recall_similar(incident_doc["description"], top_k=3)
        if similar_past:
            incident_doc["similar_past_incidents"] = [s.model_dump(mode="json") for s in similar_past]
            await inc_container.upsert_item(incident_doc)

            await event_bus.publish(incident_id, {
                "type": "memory_recalled",
                "payload": {"similar_incidents": [s.model_dump(mode="json") for s in similar_past]},
            })
    except Exception as e:
        logger.warning("memory_store.recall_error", error=str(e))

    # ── Investigation loop ────────────────────────────────────────
    # Phase 1: Parallel AutoGen agent dispatch (asyncio.gather)
    # Phase 2: Sequential AutoGen consensus chat (a_initiate_chat)
    consensus_res = None
    current_round = 1

    while current_round <= settings.MAX_INVESTIGATION_ROUNDS:
        round_num = current_round
        logger.info("investigation.round_start", incident_id=incident_id, round=round_num)

        # Build shared SwarmContext for this round
        existing_evidence = await evidence_store.get_incident_graph(incident_id)
        doc = await inc_container.read_item(item=incident_id, partition_key=incident_id)

        other_findings = []
        for f in doc.get("agent_findings", []):
            if f.get("round_number") == round_num:
                other_findings.append(AgentFinding(
                    id=f["id"],
                    incident_id=f["incident_id"],
                    agent=AgentName(f["agent"]),
                    summary=f["summary"],
                    root_cause_hypothesis=f["root_cause_hypothesis"],
                    supporting_evidence=f.get("supporting_evidence", []),
                    confidence=f["confidence"],
                    round_number=f["round_number"],
                    timestamp=f["timestamp"],
                ))

        past_incidents = [PastIncident(**s) for s in incident_doc.get("similar_past_incidents", [])]

        swarm_ctx = SwarmContext(
            incident_id=incident_id,
            incident_title=incident_doc["title"],
            incident_description=incident_doc["description"],
            severity=incident_doc["severity"],
            investigation_round=round_num,
            existing_evidence=existing_evidence,
            other_findings=other_findings,
            similar_past_incidents=past_incidents,
        )

        # ── Phase 1: Parallel AutoGen agent dispatch ──────────────
        # AutoGen's GroupChat is turn-based (one speaker at a time), so
        # we invoke each AutoGen agent's investigate() in parallel via
        # asyncio.gather for true concurrent execution.
        await add_timeline_event(
            f"Round {round_num}: Dispatching AutoGen retriever agents in parallel",
            AgentName.commander, round_num,
        )

        async def run_agent(agent, agent_name, timeline_msg, _round=round_num):
            """Run a single AutoGen agent's investigation and persist results."""
            await add_timeline_event(timeline_msg, agent_name, _round)
            try:
                finding = await agent.investigate(swarm_ctx)

                # Persist finding to Cosmos DB
                d = await inc_container.read_item(item=incident_id, partition_key=incident_id)
                d.setdefault("agent_findings", []).append(finding.model_dump(mode="json"))
                d.setdefault("agent_statuses", {})[agent_name.value] = AgentStatus.done.value
                await inc_container.upsert_item(d)

                return finding
            except Exception as e:
                logger.error(
                    f"{agent_name.value}.investigation_failed",
                    error=str(e), incident_id=incident_id,
                )
                d = await inc_container.read_item(item=incident_id, partition_key=incident_id)
                d.setdefault("agent_statuses", {})[agent_name.value] = AgentStatus.error.value
                await inc_container.upsert_item(d)
                return None

        # Parallel dispatch of AutoGen retriever agents
        results = await asyncio.gather(
            run_agent(
                log_forensics, AgentName.log_forensics,
                "Log Forensics analyzing application and system logs",
            ),
            run_agent(
                telemetry_intel, AgentName.telemetry_intel,
                "Telemetry Intelligence retrieving resource and performance metrics",
            ),
            run_agent(
                deployment_intel, AgentName.deployment_intel,
                "Deployment Intelligence checking release logs and change history",
            ),
            return_exceptions=True,
        )

        # Collect successful findings
        findings_this_round = []
        for r in results:
            if isinstance(r, AgentFinding):
                findings_this_round.append(r)
            elif isinstance(r, Exception):
                logger.error("agent.parallel_exception", error=str(r), incident_id=incident_id)

        # ── Phase 2: AutoGen Consensus chat ───────────────────────
        # Use AutoGen's a_initiate_chat between Commander and
        # ConsensusEngine for the sequential consensus phase.
        await add_timeline_event(
            "Consensus Engine executing evidence fusion pipeline",
            AgentName.consensus_engine, round_num,
        )

        await event_bus.publish(incident_id, {
            "type": "agent_status_change",
            "payload": {"agent_id": "consensus_engine", "status": "investigating"},
        })

        # Store round context for the AutoGen reply handlers
        _round_context = {
            "findings": findings_this_round,
            "round_num": round_num,
            "consensus_res": None,
            "commander_decision": None,
        }

        # Register consensus reply handler
        async def _consensus_reply(recipient, messages, sender, config):
            findings = _round_context["findings"]
            r = _round_context["round_num"]

            res = await consensus_engine.fuse(findings, incident_id, r)

            # Handle challenge rounds if conflicts exist
            if res.conflicts:
                await add_timeline_event(
                    f"Detected {len(res.conflicts)} conflict(s): initiating challenge rounds",
                    AgentName.consensus_engine, r,
                )

                challenge_ctx = SwarmContext(
                    incident_id=incident_id,
                    incident_title=incident_doc["title"],
                    incident_description=incident_doc["description"],
                    severity=incident_doc["severity"],
                    investigation_round=r,
                    existing_evidence=await evidence_store.get_incident_graph(incident_id),
                    other_findings=findings,
                    similar_past_incidents=past_incidents,
                )

                challenge_results = []
                for conflict in res.conflicts:
                    cr = await consensus_engine.request_challenge_round(
                        conflict,
                        {
                            AgentName.log_forensics: log_forensics,
                            AgentName.telemetry_intel: telemetry_intel,
                            AgentName.deployment_intel: deployment_intel,
                        },
                        challenge_ctx,
                        findings,
                    )
                    challenge_results.extend(cr)

                if challenge_results:
                    d = await inc_container.read_item(item=incident_id, partition_key=incident_id)
                    d.setdefault("challenge_results", []).extend(
                        [c.model_dump(mode="json") for c in challenge_results]
                    )
                    await inc_container.upsert_item(d)

                    await add_timeline_event(
                        "Re-fusing consensus using challenge verdicts",
                        AgentName.consensus_engine, r,
                    )
                    res = await consensus_engine.fuse(findings, incident_id, r)

            _round_context["consensus_res"] = res

            d = await inc_container.read_item(item=incident_id, partition_key=incident_id)
            d["consensus_confidence"] = res.confidence
            
            # Save conflicts to incident document so they persist on reload
            existing_conflicts = d.get("conflicts", [])
            new_conflicts = [c.model_dump(mode="json") for c in res.conflicts]
            # Merge avoiding duplicates by ID
            existing_ids = {c.get("id") for c in existing_conflicts}
            merged_conflicts = existing_conflicts + [c for c in new_conflicts if c.get("id") not in existing_ids]
            d["conflicts"] = merged_conflicts
            
            await inc_container.upsert_item(d)

            reply = (
                f"Consensus Engine fused findings.\n"
                f"Winning Hypothesis: {res.hypothesis.title}\n"
                f"Overall Confidence: {res.confidence:.4f}\n"
                f"Conflicts: {len(res.conflicts)}"
            )
            return True, reply

        consensus_agent.register_reply([autogen.Agent, None], _consensus_reply)

        # Run the AutoGen two-party chat: Commander → ConsensusEngine
        await commander_agent.a_initiate_chat(
            recipient=consensus_agent,
            message=(
                f"Round {round_num} investigation complete. "
                f"{len(findings_this_round)} agent findings collected. "
                f"Please fuse evidence and determine consensus."
            ),
            max_turns=1,
            clear_history=True,
        )

        consensus_res = _round_context["consensus_res"]

        if not consensus_res:
            logger.error("consensus.fuse_returned_none", incident_id=incident_id, round=round_num)
            current_round += 1
            continue

        # ── Commander decision ────────────────────────────────────
        proceed_override = False
        if incident_doc["severity"] == "P1" and round_num >= 2:
            proceed_override = await commander_logic.handle_p1_override(
                await inc_container.read_item(item=incident_id, partition_key=incident_id)
            )

        if consensus_res.confidence >= settings.CONFIDENCE_THRESHOLD or proceed_override:
            if proceed_override:
                await add_timeline_event(
                    "Commander issued P1 emergency fast-path override",
                    AgentName.commander, round_num,
                )
            else:
                await add_timeline_event(
                    f"Consensus confidence {consensus_res.confidence:.2f} satisfies safety threshold",
                    AgentName.commander, round_num,
                )
            break
        else:
            if current_round >= settings.MAX_INVESTIGATION_ROUNDS:
                await add_timeline_event(
                    f"Max rounds ({settings.MAX_INVESTIGATION_ROUNDS}) hit without satisfying threshold",
                    AgentName.commander, round_num,
                )
                break
            else:
                await add_timeline_event(
                    f"Consensus confidence {consensus_res.confidence:.2f} below threshold "
                    f"{settings.CONFIDENCE_THRESHOLD}; dispatching next round",
                    AgentName.commander, round_num,
                )
                current_round += 1
                continue

    # ── Phase 3: Safety Validation & Postmortem ───────────────────
    if not consensus_res:
        logger.error("investigation.completed_no_consensus", incident_id=incident_id)
        return

    doc = await inc_container.read_item(item=incident_id, partition_key=incident_id)
    doc["investigation_round"] = current_round
    await inc_container.upsert_item(doc)

    # Safety Validator with status events
    await event_bus.publish(incident_id, {
        "type": "agent_status_change",
        "payload": {"agent_id": "safety_validator", "status": "investigating"},
    })
    await add_timeline_event("Safety validation in progress", AgentName.safety_validator, current_round)

    safety_res = await safety_validator.validate(consensus_res, Incident(**doc))

    await event_bus.publish(incident_id, {
        "type": "agent_status_change",
        "payload": {"agent_id": "safety_validator", "status": "done"},
    })

    doc = await inc_container.read_item(item=incident_id, partition_key=incident_id)
    doc["safety_result"] = safety_res.model_dump(mode="json")
    doc["proposed_actions"] = [a.model_dump(mode="json") for a in safety_res.proposed_actions]

    if safety_res.approval_requests:
        doc["status"] = IncidentStatus.awaiting_approval.value
        doc["approval_status"] = ApprovalStatus.pending.value
        doc["approval_requests"] = [req.model_dump(mode="json") for req in safety_res.approval_requests]
        await inc_container.upsert_item(doc)

        app_container = await get_approvals_container()
        for req in safety_res.approval_requests:
            req_json = req.model_dump(mode="json")
            await app_container.upsert_item(req_json)
            # Emit event AFTER saving to DB to prevent frontend race condition
            await event_bus.publish(
                incident_id,
                {
                    "type": "approval_requested",
                    "payload": req_json,
                },
            )

        await add_timeline_event("Remediation actions require human approval before deployment", AgentName.safety_validator)
        logger.info("investigation.awaiting_approval", incident_id=incident_id)
    else:
        await auto_resolve_incident(doc, consensus_res, commander_logic, postmortem_agent, memory_store, inc_container)


async def auto_resolve_incident(doc, consensus_res, commander_logic, postmortem_agent, memory_store, inc_container):
    incident_id = doc["id"]
    event_bus = get_dep_event_bus()

    async def add_timeline_event(event_text: str, agent_name: AgentName | None = None):
        entry = TimelineEntry(
            timestamp=datetime.now(timezone.utc),
            event=event_text,
            agent=agent_name,
            round_number=doc.get("investigation_round", 1),
        )
        latest = await inc_container.read_item(item=incident_id, partition_key=incident_id)
        latest.setdefault("timeline", []).append(entry.model_dump(mode="json"))
        await inc_container.upsert_item(latest)
        doc["timeline"] = latest["timeline"]
        
        await event_bus.publish(incident_id, {
            "type": "timeline_updated",
            "payload": entry.model_dump(mode="json"),
        })

    await add_timeline_event("Executing automated remediation actions", AgentName.commander)

    doc["status"] = IncidentStatus.resolved.value
    doc["approval_status"] = ApprovalStatus.approved.value
    await inc_container.upsert_item(doc)

    # Emit incident_resolved event so the frontend updates the status badge
    await event_bus.publish(incident_id, {
        "type": "incident_resolved",
        "payload": {"incident_id": incident_id, "status": "resolved"},
    })

    timeline_entries = [
        TimelineEntry(
            timestamp=t["timestamp"],
            event=t["event"],
            agent=AgentName(t["agent"]) if t.get("agent") else None,
            round_number=t.get("round_number"),
        ) for t in doc.get("timeline", [])
    ]

    ctx = SwarmContext(
        incident_id=incident_id,
        incident_title=doc["title"],
        incident_description=doc["description"],
        severity=doc["severity"],
        investigation_round=doc.get("investigation_round", 1),
    )

    # Postmortem with status events
    await event_bus.publish(incident_id, {
        "type": "agent_status_change",
        "payload": {"agent_id": "postmortem_intel", "status": "investigating"},
    })
    await add_timeline_event("Generating incident postmortem report", AgentName.postmortem_intel)
    try:
        postmortem = await postmortem_agent.generate(ctx, consensus_res, timeline_entries)
        await add_timeline_event("Postmortem generated and incident closed", AgentName.postmortem_intel)
        await event_bus.publish(incident_id, {
            "type": "agent_status_change",
            "payload": {"agent_id": "postmortem_intel", "status": "done"},
        })
    except Exception as e:
        logger.error("postmortem.failed", incident_id=incident_id, error=str(e))
        await event_bus.publish(incident_id, {
            "type": "agent_status_change",
            "payload": {"agent_id": "postmortem_intel", "status": "error"},
        })

    # Final commander done
    await event_bus.publish(incident_id, {
        "type": "agent_status_change",
        "payload": {"agent_id": "commander", "status": "done"},
    })


async def resume_investigation(incident_id: str, approved: bool):
    logger.info("investigation.resume", incident_id=incident_id, approved=approved)

    inc_container = await get_incidents_container()
    try:
        incident_doc = await inc_container.read_item(item=incident_id, partition_key=incident_id)
    except Exception as e:
        logger.error("investigation.not_found", incident_id=incident_id, error=str(e))
        return

    event_bus = get_dep_event_bus()

    async def add_timeline_event(event_text: str, agent_name: AgentName | None = None):
        entry = TimelineEntry(
            timestamp=datetime.now(timezone.utc),
            event=event_text,
            agent=agent_name,
            round_number=incident_doc.get("investigation_round", 1),
        )
        latest = await inc_container.read_item(item=incident_id, partition_key=incident_id)
        latest.setdefault("timeline", []).append(entry.model_dump(mode="json"))
        await inc_container.upsert_item(latest)
        incident_doc["timeline"] = latest["timeline"]

        await event_bus.publish(incident_id, {
            "type": "timeline_updated",
            "payload": entry.model_dump(mode="json"),
        })

    llm = get_llm()
    evidence_store = get_evidence_store()
    memory_store = get_memory_store()
    commander_logic = IncidentCommander(llm, evidence_store, memory_store)
    postmortem_agent = PostmortemIntelAgent(llm, evidence_store, event_bus, memory_store)

    if approved:
        await add_timeline_event("Remediation actions approved by human", AgentName.commander)

        cons_container = await get_consensus_container()
        query = "SELECT * FROM c WHERE c.incident_id = @incident_id ORDER BY c.round_number DESC"
        parameters = [{"name": "@incident_id", "value": incident_id}]
        consensus_res = None
        async for doc in cons_container.query_items(query=query, parameters=parameters, partition_key=incident_id):
            hyp = doc["hypothesis"]
            hypothesis = Hypothesis(
                id=hyp["id"],
                incident_id=hyp["incident_id"],
                title=hyp["title"],
                description=hyp["description"],
                confidence=hyp["confidence"],
                supporting_finding_ids=hyp["supporting_finding_ids"],
                round_number=hyp["round_number"],
                timestamp=hyp["timestamp"],
            )
            conflicts = [Conflict(**c) for c in doc.get("conflicts", [])]
            consensus_res = ConsensusResult(
                incident_id=doc["incident_id"],
                hypothesis=hypothesis,
                confidence=doc["confidence"],
                conflicts=conflicts,
                round_number=doc["round_number"],
                evidence_chain=doc.get("evidence_chain", []),
                timestamp=doc["timestamp"],
            )
            break

        if consensus_res:
            await auto_resolve_incident(incident_doc, consensus_res, commander_logic, postmortem_agent, memory_store, inc_container)
        else:
            logger.error("consensus_result.not_found", incident_id=incident_id)
    else:
        await add_timeline_event("Remediation actions rejected by human", AgentName.commander)
        incident_doc["approval_status"] = ApprovalStatus.rejected.value
        await inc_container.upsert_item(incident_doc)

        next_round = incident_doc.get("investigation_round", 1) + 1
        incident_doc["status"] = IncidentStatus.investigating.value
        incident_doc["investigation_round"] = next_round
        await inc_container.upsert_item(incident_doc)

        asyncio.create_task(start_investigation_loop(incident_id, incident_doc["description"]))
