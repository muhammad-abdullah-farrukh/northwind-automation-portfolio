"""Invoice extraction contracts (brief §4.4). n8n InvoiceIQ depends on these shapes."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

JobStatus = Literal["queued", "processing", "done", "needs_review", "failed", "reviewed"]

INVOICE_FIELDS = ("vendor", "invoice_no", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "line_items")
CRITICAL_FIELDS = ("vendor", "invoice_no", "invoice_date", "total")


class LineItem(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    qty: float
    unit_price: float
    amount: float


class InvoiceData(BaseModel):
    vendor: str = Field(min_length=1, max_length=200)
    invoice_no: str = Field(min_length=1, max_length=64)
    invoice_date: date
    due_date: date | None = None
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217 code, e.g. USD")
    subtotal: float
    tax: float
    total: float
    line_items: list[LineItem] = Field(default_factory=list)

    @field_validator("currency", mode="before")
    @classmethod
    def _upper_currency(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class FieldConfidence(BaseModel):
    """The model's own 0-1 confidence per field; combined with deterministic checks in extract.py."""

    model_config = ConfigDict(extra="ignore")

    vendor: float = Field(ge=0, le=1)
    invoice_no: float = Field(ge=0, le=1)
    invoice_date: float = Field(ge=0, le=1)
    due_date: float = Field(ge=0, le=1)
    currency: float = Field(ge=0, le=1)
    subtotal: float = Field(ge=0, le=1)
    tax: float = Field(ge=0, le=1)
    total: float = Field(ge=0, le=1)
    line_items: float = Field(ge=0, le=1)


class LLMInvoiceOutput(InvoiceData):
    """What the extraction prompt asks the LLM for."""

    field_confidence: FieldConfidence


class ValidationIssue(BaseModel):
    field: str
    code: str
    message: str


class Validation(BaseModel):
    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)


class Confidence(BaseModel):
    overall: float
    fields: dict[str, float] = Field(default_factory=dict)


class ExtractMeta(BaseModel):
    model: str | None
    prompt_version: str
    tokens: int
    cost_usd: float | None
    latency_ms: int


class ExtractResponse(BaseModel):
    job_id: str
    status: JobStatus
    duplicate_of: str | None
    data: InvoiceData | None
    confidence: Confidence
    validation: Validation
    meta: ExtractMeta


class JobCreated(BaseModel):
    job_id: str
    status: JobStatus


class JobSummary(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    filename: str | None
    vendor: str | None
    invoice_no: str | None
    total: float | None
    currency: str | None
    confidence: float | None
    duplicate_of: str | None


class ReviewRequest(BaseModel):
    data: InvoiceData
    notes: str | None = Field(default=None, max_length=2000)


class ReviewResult(BaseModel):
    job_id: str
    status: JobStatus
    validation: Validation
