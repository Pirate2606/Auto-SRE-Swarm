import structlog
from fastapi import APIRouter, BackgroundTasks, Request
from datetime import datetime, timezone

from app.models import IncidentCreate, Severity
from orchestrator.manager import start_investigation
from api.routes_incident import create_incident

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/webhook")

@router.post("/azure-monitor")
async def azure_monitor_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives alerts from Azure Monitor Action Groups (Common Alert Schema).
    Extracts the relevant metrics/logs and initiates a Swarm investigation.
    """
    payload = await request.json()
    
    # Check if this is the Common Alert Schema
    schema_id = payload.get("schemaId")
    data = payload.get("data", {})
    
    if schema_id == "azureMonitorCommonAlertSchema":
        alert_context = data.get("alertContext", {})
        essentials = data.get("essentials", {})
        alert_name = essentials.get("alertRule", "Azure Monitor Alert")
        severity_str = essentials.get("severity", "Sev3")
        description = essentials.get("description", "No description provided")
        targets = essentials.get("alertTargetIDs", [])
        resource_id = targets[0] if targets else "Unknown Resource"
        condition = alert_context.get("condition", {})
    elif schema_id == "AzureMonitorMetricAlert":
        context = data.get("context", {})
        alert_name = context.get("name", "Azure Monitor Alert")
        severity_str = str(context.get("severity", "Sev3"))
        description = context.get("description", "No description provided")
        resource_id = context.get("resourceId", "Unknown Resource")
        condition = context.get("condition", {})
    else:
        logger.warning("webhook.azure_monitor.invalid_schema", schema_id=schema_id)
        return {"status": "ignored", "reason": "Unsupported schema"}
    
    # Map Azure Severity to our Severity enum
    severity_map = {
        "Sev0": Severity.P1,
        "Sev1": Severity.P1,
        "Sev2": Severity.P2,
        "Sev3": Severity.P3,
        "Sev4": Severity.P3,
        "0": Severity.P1,
        "1": Severity.P1,
        "2": Severity.P2,
        "3": Severity.P3,
        "4": Severity.P3,
    }
    incident_severity = severity_map.get(severity_str, Severity.P2)
    
    # 2. Extract Condition Details (Metrics or Log Query)
    condition_details = ""
    if condition.get("allOf"):
        for cond in condition["allOf"]:
            metric_name = cond.get("metricName", cond.get("searchQuery", "Unknown Condition"))
            metric_val = cond.get("metricValue", "N/A")
            operator = cond.get("operator", "")
            threshold = cond.get("threshold", "")
            condition_details += f"- {metric_name} {operator} {threshold} (Current: {metric_val})\n"
            
    full_description = (
        f"Azure Monitor Alert Triggered on {resource_id}\n\n"
        f"**Alert Description**: {description}\n"
        f"**Conditions Met**:\n{condition_details}\n"
    )
    
    # 3. Create Incident in Swarm
    incident_data = IncidentCreate(
        title=alert_name,
        description=full_description,
        severity=incident_severity,
        source="azure_monitor",
        metadata={
            "resource_id": resource_id,
            "raw_alert": payload
        }
    )
    
    # Reuse the logic from create_incident endpoint
    response = await create_incident(incident_data, background_tasks)
    
    logger.info("webhook.azure_monitor.incident_created", incident_id=response.id, title=alert_name)
    
    return {"status": "success", "incident_id": response.id}
