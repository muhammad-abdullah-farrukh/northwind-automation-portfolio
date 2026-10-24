import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import extract, health, jobs, leads
from app.core.config import get_settings
from app.core.deps import build_resources, close_resources
from app.core.logging import request_id_var, setup_logging

log = logging.getLogger("opscore")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    app.state.resources = build_resources(settings)
    log.info(
        "opscore started",
        extra={"llm_provider": settings.llm_provider, "llm_model_fast": settings.llm_model_fast, "version": settings.app_version},
    )
    yield
    await close_resources(app.state.resources)


app = FastAPI(
    title="OpsCore",
    version=get_settings().app_version,
    description=(
        "Northwind Digital's automation engine. No-code flows (Zapier LeadRouter, n8n InvoiceIQ) decide what "
        "happens; OpsCore decides what the data is. Auth: `X-API-Key` header."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"path": request.url.path})
        response = JSONResponse({"detail": "internal error", "request_id": rid}, status_code=500)
    latency_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = rid
    log.info(
        "request",
        extra={"method": request.method, "path": request.url.path, "status": response.status_code, "latency_ms": latency_ms},
    )
    request_id_var.reset(token)
    return response


app.include_router(health.router)
app.include_router(leads.router)
app.include_router(extract.router)
app.include_router(jobs.router)
