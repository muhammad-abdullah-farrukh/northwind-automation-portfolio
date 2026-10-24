"""The single repair pass: re-prompt with the validation errors."""

import json
from typing import Any

from app.models.invoice import ValidationIssue

REPAIR_PROMPT_VERSION = "invoice_repair_v1"


def build_repair_message(template: str, *, invoice_text: str, previous: Any, errors: list[ValidationIssue]) -> str:
    listed = "\n".join(f"- {e.field}: {e.message}" for e in errors) or "- (none)"
    previous_json = json.dumps(previous, indent=2, default=str) if not isinstance(previous, str) else previous
    return (
        template.replace("{{ERRORS}}", listed)
        .replace("{{PREVIOUS}}", previous_json)
        .replace("{{INVOICE_TEXT}}", invoice_text)
    )
