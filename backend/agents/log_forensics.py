import os
import autogen
from datetime import timedelta, datetime, timezone
import structlog
from azure.identity.aio import DefaultAzureCredential
from azure.monitor.query.aio import LogsQueryClient

from app.models import AgentName
from agents.base import SwarmAgent, SwarmContext

logger = structlog.get_logger(__name__)

class LogForensicsAgent(SwarmAgent):
    name = AgentName.log_forensics
    role_prompt = (
        "You are the Log Forensics Agent in an autonomous SRE swarm.\n"
        "Your speciality: application and system log analysis.\n"
        "You identify: error patterns, exception cascades, OOM signals, connection pool "
        "exhaustion, stack traces, anomalous log volume spikes, and correlated error sequences.\n"
        "You must: cite specific log messages, provide exact timestamps, identify the first "
        "occurrence of each error pattern.\n"
        "You must not: speculate beyond what the logs show. If logs are ambiguous, say so and "
        "lower your confidence.\n"
        "Output a structured finding with root cause hypothesis and confidence score."
    )

    def __init__(self, llm, evidence_store, event_bus):
        super().__init__(llm, evidence_store, event_bus)

        async def fetch_logs(service: str, time_window_minutes: int = 30) -> str:
            """Fetch application logs (AppTraces and AppExceptions) for a specific time window using KQL."""
            workspace_id = os.environ.get("AZURE_WORKSPACE_ID")
            if not workspace_id:
                return "Error: AZURE_WORKSPACE_ID not set. Running in mock/disconnected mode."

            try:
                credential = DefaultAzureCredential()
                client = LogsQueryClient(credential)
                
                # Query Application Insights tables for logs and exceptions
                query = f"""
                union AppTraces, AppExceptions
                | where TimeGenerated > ago({time_window_minutes}m)
                | project TimeGenerated, Type, Message, ExceptionType, ItemType, SeverityLevel
                | order by TimeGenerated desc
                | take 50
                """
                
                response = await client.query_workspace(workspace_id, query, timespan=timedelta(minutes=time_window_minutes))
                await client.close()
                await credential.close()

                if response.status == "Failure":
                    return f"Error executing KQL: {response.error}"
                
                if not response.tables:
                    return "No logs found."
                    
                table = response.tables[0]
                log_lines = []
                for row in table.rows:
                    time_gen = row[0]
                    record_type = row[1]
                    message = row[2] or ""
                    exc_type = row[3] or ""
                    sev = row[5] or "INFO"
                    
                    exc_part = f" | EXCEPTION: {exc_type}" if exc_type else ""
                    msg_preview = message[:500] + "..." if len(message) > 500 else message
                    
                    log_lines.append(f"[{time_gen}] [{sev}] [{record_type}] {msg_preview}{exc_part}")
                
                return "\n".join(log_lines) or "No logs found."
            except Exception as e:
                logger.error("log_forensics.fetch_logs_error", error=str(e))
                return f"Failed to fetch logs: {str(e)}"

        autogen.agentchat.register_function(
            fetch_logs,
            caller=self,
            executor=self,
            name="fetch_logs",
            description="Query application and system logs to identify error cascades.",
        )

    async def _fetch_domain_data(self, ctx: SwarmContext) -> dict:
        # For the initial context, fetch the last 30 mins of logs automatically
        # We invoke the registered tool function directly
        workspace_id = os.environ.get("AZURE_WORKSPACE_ID")
        if not workspace_id:
            logger.warning("log_forensics.missing_workspace_id", incident_id=ctx.incident_id)
            return {"logs": "Running in disconnected mode. No logs available.", "alerts": "(not integrated)"}

        try:
            credential = DefaultAzureCredential()
            client = LogsQueryClient(credential)
            
            query = """
            union AppTraces, AppExceptions
            | where TimeGenerated > ago(30m)
            | project TimeGenerated, Type, Message, ExceptionType, SeverityLevel
            | order by TimeGenerated desc
            | take 50
            """
            
            response = await client.query_workspace(workspace_id, query, timespan=timedelta(minutes=30))
            await client.close()
            await credential.close()

            if response.status == "Failure" or not response.tables:
                logs_str = "(no logs returned)"
            else:
                table = response.tables[0]
                lines = []
                for row in table.rows:
                    time_gen, rtype, msg, exc, sev = row[0], row[1], row[2], row[3], row[4]
                    lines.append(f"[{time_gen}] [{sev}] {msg} {exc if exc else ''}")
                logs_str = "\n".join(lines)
        except Exception as e:
            logs_str = f"Error fetching initial logs: {str(e)}"

        return {"logs": logs_str, "alerts": "(use fetch_logs for deeper queries)"}

    def _get_investigation_prompt(self, ctx: SwarmContext, domain_data: dict) -> str:
        logs_str = domain_data["logs"]
        alerts = domain_data["alerts"]

        return (
            f"## Log Data (Last 30 mins, Top 50 entries)\n\n"
            f"```\n{logs_str}\n```\n\n"
            f"## Active Alerts\n{alerts}\n\n"
            f"## Instructions\n"
            f"1. Identify the primary error pattern in these logs.\n"
            f"2. Find the first occurrence of that pattern and note the timestamp.\n"
            f"3. Look for exception cascades or correlated errors.\n"
            f"4. Estimate the root cause based on log evidence alone.\n"
            f"5. Score your confidence 0.0–1.0. If logs are ambiguous, lower confidence.\n"
        )
