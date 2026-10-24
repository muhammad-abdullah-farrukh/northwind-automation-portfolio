from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz", summary="Liveness plus database and Redis reachability")
async def healthz(request: Request) -> JSONResponse:
    res = request.app.state.resources
    checks = {"db": False, "redis": False}
    try:
        async with res.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = True
    except Exception:  # noqa: BLE001 - health endpoint reports, never raises
        pass
    try:
        checks["redis"] = bool(await res.redis.ping())
    except Exception:  # noqa: BLE001
        pass
    ok = all(checks.values())
    body = {"status": "ok" if ok else "degraded", **checks, "version": request.app.version}
    return JSONResponse(body, status_code=200 if ok else 503)
