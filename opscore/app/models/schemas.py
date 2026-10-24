from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SizeBand = Literal["1-10", "11-50", "51-200", "201-1000", "1000+", "unknown"]


class EnrichRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")  # Zapier may send extra form fields

    email: str = Field(max_length=320)
    website: str | None = Field(default=None, max_length=2048)
    company: str | None = Field(default=None, max_length=256)
    name: str | None = Field(default=None, max_length=256)


class EnrichResponse(BaseModel):
    """Contract consumed by LeadRouter (brief §4.4). Field names and order are fixed."""

    email: str
    domain: str
    mx_valid: bool
    is_free_mail: bool
    is_disposable: bool
    website_reachable: bool
    site_summary: str | None
    industry_guess: str | None
    size_band_guess: SizeBand | None
    rule_score: int = Field(ge=0, le=100)
    enrich_confidence: float = Field(ge=0, le=1)
    cached: bool
    note: str


class SiteGuess(BaseModel):
    """What the LLM must return for a homepage (prompts/site_enrich_v1.md)."""

    site_summary: str = Field(max_length=400)
    industry_guess: str = Field(max_length=80)
    # The model only reports a number it read; code maps it to a band (scoring.size_band_for, DECISIONS D23).
    employee_count_stated: int | None = Field(default=None, ge=1, le=10_000_000)
    confidence: float = Field(ge=0, le=1)


class ErrorBody(BaseModel):
    detail: str
    request_id: str | None = None
