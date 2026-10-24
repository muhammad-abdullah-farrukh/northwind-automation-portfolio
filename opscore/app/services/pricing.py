"""List prices (USD per 1M tokens) for cost *estimates*.

Source: Anthropic first-party list prices from the claude-api reference (cached 2026-06-24).
When calls go through a gateway (e.g. AgentRouter) the actual charge differs, so reports
label these numbers "list-price estimate". Unknown models return None, never a guess.
"""

PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = PRICES_PER_MTOK.get(model)
    if price is None:
        return None
    return round((input_tokens * price[0] + output_tokens * price[1]) / 1_000_000, 6)
