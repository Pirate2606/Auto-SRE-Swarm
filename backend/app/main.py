import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from api import routes_incident, routes_approval, routes_ws, routes_webhook
from db.database import init_db, close_db
from services.event_bus import init_event_bus

# Correlation ID context variable
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# Custom processor for context IDs
def add_context_ids(logger, log_method, event_dict):
    req_id = request_id_ctx.get()
    if req_id:
        event_dict["request_id"] = req_id
    return event_dict

def configure_structlog(log_level: str):
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    processors = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        add_context_ids,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if log_level.upper() == "DEBUG":
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log the request
            structlog.get_logger("http.request").info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_ctx.reset(token)

settings = get_settings()
configure_structlog(settings.LOG_LEVEL)

logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up auto-sre-swarm backend...")
    await init_db()
    await init_event_bus()
    yield
    logger.info("Shutting down auto-sre-swarm backend...")
    await close_db()

app = FastAPI(lifespan=lifespan, title="Auto SRE Swarm API")

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_incident.router, tags=["incidents"])
app.include_router(routes_approval.router, tags=["approvals"])
app.include_router(routes_ws.router, tags=["websocket"])
app.include_router(routes_webhook.router, tags=["webhook"])
