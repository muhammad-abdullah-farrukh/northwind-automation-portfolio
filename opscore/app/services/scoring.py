"""Deterministic scores. Weights are documented in DECISIONS.md; change them there too."""

SIZE_BANDS = ((10, "1-10"), (50, "11-50"), (200, "51-200"), (1000, "201-1000"))


def size_band_for(employee_count: int | None) -> str:
    """Deterministic banding of a headcount the page states; a 4B model put 350 employees in 51-200."""
    if not employee_count or employee_count < 1:
        return "unknown"
    for upper, band in SIZE_BANDS:
        if employee_count <= upper:
            return band
    return "1000+"


# Northwind (a 20-person agency) sells best to small and mid-size companies.
SIZE_POINTS = {"11-50": 15, "51-200": 15, "201-1000": 10, "1-10": 5, "1000+": 5, "unknown": 0}

ICP_INDUSTRY_KEYWORDS = (
    "saas", "software", "e-commerce", "ecommerce", "retail", "logistics", "fintech",
    "health", "marketing", "agency", "professional services", "real estate", "education", "travel",
)  # fmt: skip


def rule_score(
    *,
    mx_valid: bool,
    is_free_mail: bool,
    is_disposable: bool,
    website_reachable: bool,
    industry_guess: str | None,
    size_band_guess: str | None,
) -> int:
    score = 0
    score += 20 if mx_valid else 0
    score += 20 if not is_free_mail else 0
    score += 10 if not is_disposable else 0
    score += 15 if website_reachable else 0
    industry = (industry_guess or "").lower()
    if industry and industry != "unknown":
        score += 10
        if any(k in industry for k in ICP_INDUSTRY_KEYWORDS):
            score += 10
    score += SIZE_POINTS.get(size_band_guess or "unknown", 0)
    if is_disposable:
        score = min(score, 5)
    return max(0, min(100, score))


def enrich_confidence(
    *,
    website_reachable: bool,
    text_chars: int,
    llm_ok: bool,
    llm_confidence: float,
    industry_guess: str | None,
    size_band_guess: str | None,
) -> float:
    """0 when there is nothing to go on; otherwise half evidence coverage, half the model's own confidence."""
    if not website_reachable:
        return 0.0
    signals = [
        True,  # reachable
        text_chars >= 500,
        llm_ok,
        bool(industry_guess) and industry_guess.lower() != "unknown",
        bool(size_band_guess) and size_band_guess != "unknown",
    ]
    coverage = sum(signals) / len(signals)
    model_part = max(0.0, min(1.0, llm_confidence)) if llm_ok else 0.0
    return round(0.5 * coverage + 0.5 * model_part, 2)
