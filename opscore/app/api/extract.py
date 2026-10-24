import hashlib

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_api_key
from app.core.config import Settings, get_settings
from app.core.deps import get_llm, get_session
from app.core.idempotency import run_idempotent
from app.models.db import ApiKey
from app.models.invoice import ExtractResponse
from app.models.schemas import ErrorBody
from app.services.extract import process_document
from app.services.llm import LLMClient

router = APIRouter(prefix="/v1/extract", tags=["extract"])
SUPPORTED_SCHEMAS = {"invoice"}


@router.post(
    "/sync",
    response_model=ExtractResponse,
    summary="Extract and validate an invoice PDF (up to 5 pages), synchronously",
    responses={
        401: {"model": ErrorBody},
        409: {"model": ErrorBody, "description": "Idempotency-Key reused with a different file"},
        413: {"model": ErrorBody, "description": "File too large or too many pages for sync"},
        415: {"model": ErrorBody, "description": "Not a PDF"},
        422: {"model": ErrorBody, "description": "Unknown schema or unreadable PDF"},
        503: {"model": ErrorBody, "description": "LLM unavailable; retry later"},
    },
)
async def extract_sync(
    file: UploadFile = File(..., description="Invoice PDF with a text layer"),
    schema_name: str = Form("invoice", alias="schema"),
    api_key: ApiKey = Depends(require_api_key),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    if schema_name not in SUPPORTED_SCHEMAS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unsupported schema {schema_name!r}; available: {sorted(SUPPORTED_SCHEMAS)}")
    content = await file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"file exceeds {settings.upload_max_bytes} bytes")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "empty file")

    async def handler() -> tuple[int, dict]:
        result = await process_document(
            session, api_key_id=api_key.id, content=content, filename=file.filename, llm=llm, settings=settings
        )
        return 200, result.model_dump(mode="json")

    return await run_idempotent(
        session,
        api_key_id=api_key.id,
        endpoint="POST /v1/extract/sync",
        idem_key=idempotency_key,
        body={"file_sha256": hashlib.sha256(content).hexdigest(), "schema": schema_name},
        handler=handler,
    )
