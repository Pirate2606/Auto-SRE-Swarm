import autogen
from app.models import AgentName
from agents.base import SwarmAgent, SwarmContext


class DeploymentIntelAgent(SwarmAgent):
    name = AgentName.deployment_intel
    role_prompt = (
        "You are the Deployment Intelligence Agent in an autonomous SRE swarm.\n"
        "Your speciality: change management — deployments, config changes, feature flags.\n"
        "You identify: deployments within 2 hours of incident start, config drift, feature "
        "flag activations, version regressions, and correlations between changes and failure "
        "onset.\n"
        "You must: cite specific deployment IDs, versions, and changelogs. Temporal correlation "
        "is not causation — always note when you are inferring.\n"
        "If no changes in 48 hours, explicitly state this as evidence against deploy-related "
        "root cause."
    )

    def __init__(self, llm, evidence_store, event_bus):
        super().__init__(llm, evidence_store, event_bus)

        async def fetch_deployments(lookback_hours: int = 48) -> str:
            """Fetch recent deployments and configuration changes."""
            if not self._current_incident_id:
                return "Error: No active incident context."
            from services.mock_cloud import MockCloudService
            mock_cloud = MockCloudService()
            result = await mock_cloud.get_deployments(self._current_incident_id, lookback_hours)
            lines = []
            for d in result.deployments:
                lines.append(
                    f"[{d.deployed_at.isoformat()}] {d.service} v{d.version} by {d.deployed_by} "
                    f"(status={d.status}): {d.changelog}"
                )
            return "\n".join(lines) or "No deployments found in the lookback window."

        autogen.agentchat.register_function(
            fetch_deployments,
            caller=self,
            executor=self,
            name="fetch_deployments",
            description="Fetch release deployment history and change logs.",
        )

    async def _fetch_domain_data(self, ctx: SwarmContext) -> dict:
        deployments = await ctx.mock_cloud.get_deployments(
            incident_id=ctx.incident_id,
            lookback_hours=48,
        )
        return {"deployments": deployments}

    def _get_investigation_prompt(self, ctx: SwarmContext, domain_data: dict) -> str:
        deploy_history = domain_data["deployments"]
        deploys = deploy_history.deployments

        if deploys:
            deploy_lines: list[str] = []
            for d in deploys:
                deploy_lines.append(
                    f"[{d.deployed_at.isoformat()}] {d.service} v{d.version} "
                    f"by {d.deployed_by} (status={d.status}): {d.changelog}"
                )
            deploy_block = "\n".join(deploy_lines)
        else:
            deploy_block = "(no deployments in the last 48 hours)"

        return (
            f"## Deployment History (last 48 hours)\n"
            f"Total deployments found: {len(deploys)}\n\n"
            f"```\n{deploy_block}\n```\n\n"
            f"## Instructions\n"
            f"1. Check for deployments within 2 hours of the incident start time.\n"
            f"2. If a deployment exists, assess temporal correlation with the failure. "
            f"Note: temporal correlation is NOT causation.\n"
            f"3. Review changelogs for potentially risky changes (routing, database, "
            f"auth, config).\n"
            f"4. If NO deployments occurred, explicitly state that the evidence argues "
            f"against a deploy-related root cause.\n"
            f"5. Score your confidence 0.0–1.0.\n"
        )
