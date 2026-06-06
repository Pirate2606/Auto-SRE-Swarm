import os
import autogen
from datetime import timedelta
import structlog
from azure.identity.aio import DefaultAzureCredential
from azure.monitor.query.aio import LogsQueryClient

from app.models import AgentName
from agents.base import SwarmAgent, SwarmContext

logger = structlog.get_logger(__name__)

class TelemetryIntelAgent(SwarmAgent):
    name = AgentName.telemetry_intel
    role_prompt = (
        "You are the Telemetry Intelligence Agent in an autonomous SRE swarm.\n"
        "Your speciality: metrics, APM data, latency distributions, saturation signals.\n"
        "You identify: memory/CPU saturation, latency percentile spikes (p95/p99), error "
        "rate trends, traffic anomalies, resource exhaustion patterns, and leading indicators "
        "of failure.\n"
        "You must: cite specific metric names, values, and timestamps. Identify the exact "
        "point where metrics deviated from baseline.\n"
        "You must not: confuse correlation with causation. If metrics are ambiguous, provide "
        "both interpretations with respective confidence."
    )

    def __init__(self, llm, evidence_store, event_bus):
        super().__init__(llm, evidence_store, event_bus)

        async def fetch_metrics() -> str:
            """Fetch request metrics (RPS, Latency, Error Rate) for the last 30 minutes from Azure Log Analytics."""
            workspace_id = os.environ.get("AZURE_WORKSPACE_ID")
            if not workspace_id:
                return "Error: AZURE_WORKSPACE_ID not set. Running in mock mode."
            
            try:
                credential = DefaultAzureCredential()
                client = LogsQueryClient(credential)
                
                # Query Application Insights for RPS, Error Rate, and Latency
                query = """
                AppRequests
                | where TimeGenerated > ago(30m)
                | summarize 
                    RPS = count() / 60.0,
                    ErrorRate = countif(Success == false) * 1.0 / count(),
                    p50_Latency = percentile(DurationMs, 50),
                    p95_Latency = percentile(DurationMs, 95),
                    p99_Latency = percentile(DurationMs, 99)
                  by bin(TimeGenerated, 1m)
                | order by TimeGenerated desc
                | take 30
                """
                
                response = await client.query_workspace(workspace_id, query, timespan=timedelta(minutes=30))
                await client.close()
                await credential.close()

                if response.status == "Failure" or not response.tables:
                    return "No metrics found."
                    
                table = response.tables[0]
                lines = ["| Time | RPS | ErrorRate | p50 (ms) | p95 (ms) | p99 (ms) |"]
                lines.append("|---|---|---|---|---|---|")
                for row in table.rows:
                    tg, rps, err, p50, p95, p99 = row
                    lines.append(f"| {tg} | {rps:.1f} | {err:.3f} | {p50:.1f} | {p95:.1f} | {p99:.1f} |")
                
                return "\n".join(lines)
            except Exception as e:
                logger.error("telemetry_intel.fetch_metrics_error", error=str(e))
                return f"Failed to fetch metrics: {str(e)}"

        autogen.agentchat.register_function(
            fetch_metrics,
            caller=self,
            executor=self,
            name="fetch_metrics",
            description="Query Azure Monitor for Request metrics (RPS, Latency, Error Rate).",
        )

    async def _fetch_domain_data(self, ctx: SwarmContext) -> dict:
        workspace_id = os.environ.get("AZURE_WORKSPACE_ID")
        if not workspace_id:
            logger.warning("telemetry_intel.missing_workspace_id", incident_id=ctx.incident_id)
            return {"metrics": "Running in disconnected mode. No metrics available.", "apm": "(not integrated)"}

        try:
            credential = DefaultAzureCredential()
            client = LogsQueryClient(credential)
            
            # Get a quick snapshot of the last 5 minutes
            query = """
            AppRequests
            | where TimeGenerated > ago(5m)
            | summarize 
                TotalRequests = count(),
                ErrorRate = countif(Success == false) * 1.0 / count(),
                AvgLatency = avg(DurationMs)
            """
            
            response = await client.query_workspace(workspace_id, query, timespan=timedelta(minutes=5))
            await client.close()
            await credential.close()

            if response.status == "Failure" or not response.tables:
                metrics_str = "(no metrics returned)"
            else:
                table = response.tables[0]
                if table.rows:
                    reqs, err, lat = table.rows[0]
                    metrics_str = f"Last 5m Snapshot - Requests: {reqs}, Error Rate: {err:.3f}, Avg Latency: {lat:.1f}ms"
                else:
                    metrics_str = "(no metrics in last 5 mins)"
        except Exception as e:
            metrics_str = f"Error fetching initial metrics: {str(e)}"

        return {"metrics": metrics_str, "apm": "(use fetch_metrics tool for time-series data)"}

    def _get_investigation_prompt(self, ctx: SwarmContext, domain_data: dict) -> str:
        metrics_str = domain_data["metrics"]
        apm = domain_data["apm"]

        return (
            f"## Telemetry Snapshot (Last 5 mins)\n\n"
            f"{metrics_str}\n\n"
            f"## APM\n{apm}\n\n"
            f"## Instructions\n"
            f"1. Use `fetch_metrics` to get a 30-minute time-series breakdown.\n"
            f"2. Identify metric anomalies — look for sudden changes, trends, or threshold breaches.\n"
            f"3. Determine if the cause is traffic-driven (RPS spike) or resource-driven.\n"
            f"4. Score your confidence 0.0–1.0.\n"
        )
