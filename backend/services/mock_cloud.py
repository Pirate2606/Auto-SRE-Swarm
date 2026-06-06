import hashlib
import random
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel

class LogRow(BaseModel):
    timestamp: datetime
    level: str
    message: str
    exception: Optional[str] = None
    trace_id: str
    service: str
    pod: str

class LogQueryResult(BaseModel):
    query_time: datetime
    rows: List[LogRow]
    total_count: int

class MetricDataPoint(BaseModel):
    timestamp: datetime
    value: float
    unit: str

class MetricQueryResult(BaseModel):
    metric_name: str
    interval: str
    series: List[MetricDataPoint]

class DeploymentRecord(BaseModel):
    id: str
    service: str
    version: str
    deployed_at: datetime
    deployed_by: str
    status: str
    changelog: str

class DeploymentHistory(BaseModel):
    deployments: List[DeploymentRecord]

class AlertRecord(BaseModel):
    alert_name: str
    severity: str
    fired_at: datetime
    service: str
    description: str

class APMSnapshot(BaseModel):
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate: float
    rps: float
    saturation: float

class MockCloudService:
    async def _get_scenario(self, incident_id: str) -> str:
        from db.database import get_incidents_container
        description = "OOM"
        try:
            container = await get_incidents_container()
            doc = await container.read_item(item=incident_id, partition_key=incident_id)
            if doc and doc.get("description"):
                description = doc["description"].lower()
        except Exception:
            pass  # DB fallback
        
        if "memory" in description or "oom" in description or "leak" in description:
            return "OOM"
        elif "deploy" in description or "release" in description:
            return "Bad Deploy"
        elif "traffic" in description or "ddos" in description or "spike" in description:
            return "Traffic Spike / DDoS"
        elif "dependency" in description or "upstream" in description or "timeout" in description:
            return "Dependency Failure"
        
        return "OOM"

    def _get_random(self, incident_id: str, salt: str) -> random.Random:
        seed = int(hashlib.md5(f"{incident_id}_{salt}".encode()).hexdigest(), 16)
        return random.Random(seed)

    def _jitter(self, val: float, r: random.Random) -> float:
        return val * (1.0 + (r.random() * 0.2 - 0.1))

    async def get_logs(self, incident_id: str, service: str, time_window_minutes: int = 30) -> LogQueryResult:
        scenario = await self._get_scenario(incident_id)
        r = self._get_random(incident_id, f"logs_{service}")
        
        now = datetime.utcnow()
        rows = []
        count = r.randint(20, 50)
        for i in range(count):
            ts = now - timedelta(minutes=r.random() * time_window_minutes)
            if scenario == "OOM":
                msg = "OutOfMemoryException: Java heap space" if r.random() > 0.5 else "GC Overhead limit exceeded"
                lvl = "ERROR"
            elif scenario == "Bad Deploy":
                msg = "NullReferenceException in newly deployed module"
                lvl = "ERROR"
            elif scenario == "Traffic Spike / DDoS":
                msg = "Rate limit exceeded for IP"
                lvl = "WARN"
            elif scenario == "Dependency Failure":
                msg = "Upstream connection timeout"
                lvl = "ERROR"
            else:
                msg = "System log entry"
                lvl = "INFO"
            
            rows.append(LogRow(
                timestamp=ts,
                level=lvl,
                message=msg,
                exception=msg if lvl == "ERROR" else None,
                trace_id=f"trace-{r.randint(1000, 9999)}",
                service=service,
                pod=f"{service}-pod-{r.randint(1, 5)}"
            ))
        rows.sort(key=lambda x: x.timestamp)
        return LogQueryResult(query_time=now, rows=rows, total_count=count)

    async def get_metrics(self, incident_id: str, service: str, metric_names: list[str]) -> MetricQueryResult:
        scenario = await self._get_scenario(incident_id)
        r = self._get_random(incident_id, f"metrics_{service}_{metric_names[0] if metric_names else 'metric'}")
        now = datetime.utcnow()
        
        series = []
        for i in range(30):
            ts = now - timedelta(minutes=30-i)
            val = 50.0
            if scenario == "OOM":
                val = 50.0 + i * 1.5
                if val > 95: val = 95 + r.random() * 4
            elif scenario == "Traffic Spike / DDoS":
                val = 1000.0 if i > 15 else 100.0
            elif scenario == "Dependency Failure":
                val = 2000.0 if i > 15 else 200.0
            
            series.append(MetricDataPoint(
                timestamp=ts,
                value=self._jitter(val, r),
                unit="percent" if scenario == "OOM" else "ms"
            ))
            
        return MetricQueryResult(metric_name=metric_names[0] if metric_names else "metric", interval="1m", series=series)

    async def get_deployments(self, incident_id: str, lookback_hours: int = 48) -> DeploymentHistory:
        scenario = await self._get_scenario(incident_id)
        r = self._get_random(incident_id, "deployments")
        now = datetime.utcnow()
        
        deps = []
        if scenario == "Bad Deploy":
            deps.append(DeploymentRecord(
                id=f"deploy-{r.randint(100, 999)}",
                service="api-gateway",
                version="v2.1.0",
                deployed_at=now - timedelta(minutes=110),
                deployed_by="ci-cd",
                status="success",
                changelog="Updated routing logic"
            ))
        
        return DeploymentHistory(deployments=deps)

    async def get_alerts(self, incident_id: str) -> list[AlertRecord]:
        scenario = await self._get_scenario(incident_id)
        now = datetime.utcnow()
        return [AlertRecord(
            alert_name=f"{scenario} Alert",
            severity="High",
            fired_at=now - timedelta(minutes=15),
            service="api-gateway",
            description=f"Automated alert for {scenario}"
        )]

    async def get_apm_data(self, incident_id: str, service: str) -> APMSnapshot:
        scenario = await self._get_scenario(incident_id)
        r = self._get_random(incident_id, f"apm_{service}")
        
        p50 = 50.0
        p95 = 100.0
        p99 = 200.0
        err = 0.01
        rps = 100.0
        sat = 0.5
        
        if scenario == "OOM":
            p99 = 5000.0
        elif scenario == "Bad Deploy":
            err = 0.25
        elif scenario == "Traffic Spike / DDoS":
            rps = 1000.0
        elif scenario == "Dependency Failure":
            p50, p95, p99 = 1000.0, 2000.0, 5000.0
            
        return APMSnapshot(
            p50_latency_ms=self._jitter(p50, r),
            p95_latency_ms=self._jitter(p95, r),
            p99_latency_ms=self._jitter(p99, r),
            error_rate=self._jitter(err, r),
            rps=self._jitter(rps, r),
            saturation=self._jitter(sat, r)
        )
