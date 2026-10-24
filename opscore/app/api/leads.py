from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.config import Settings, get_settings
from app.core.deps import get_llm, get_session
from app.core.idempotency import run_idempotent
from app.models.db import ApiKey
from app.models.schemas import EnrichRequest, EnrichResponse, ErrorBody
from app.services.enrich import enrich_lead
from app.services.llm import LLMClient

router = APIRouter(prefix="/v1/leads", tags=["leads"])


@router.post(
    "/enrich",
    response_model=EnrichResponse,
    summary="Validate, enrich and rule-score a lead (sync, < 5 s)",
    responses={
        401: {"model": ErrorBody},
        409: {"model": ErrorBody, "description": "Idempotency-Key reused with a different body"},
        422: {"model": ErrorBody, "description": "Email is not syntactically valid"},
        429: {"model": ErrorBody},
    },
)
async def enrich(
    req: EnrichRequest,
    api_key: ApiKey = Depends(require_api_key),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    async def handler() -> tuple[int, dict]:
        result = await enrich_lead(req, session=session, llm=llm, settings=settings)
        return 200, result.model_dump(mode="json")

    return await run_idempotent(
        session,
        api_key_id=api_key.id,
        endpoint="POST /v1/leads/enrich",
        idem_key=idempotency_key,
        body=req.model_dump(mode="json"),
        handler=handler,
    )
