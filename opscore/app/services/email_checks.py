"""Email syntax, MX and free-mail / disposable classification."""

import logging
from functools import lru_cache
from pathlib import Path

import dns.asyncresolver
import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class InvalidEmail(ValueError):
    pass


def normalize_email(raw: str) -> tuple[str, str]:
    """Return (normalized_email, domain). Syntax only; no DNS."""
    try:
        result = validate_email(raw.strip(), check_deliverability=False)
    except EmailNotValidError as exc:
        raise InvalidEmail(str(exc)) from exc
    email = f"{result.local_part}@{result.domain}".lower()
    return email, result.domain.lower()


@lru_cache
def _domain_set(filename: str) -> frozenset[str]:
    lines = (DATA_DIR / filename).read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().lower() for line in lines if line.strip() and not line.startswith("#"))


def is_free_mail(domain: str) -> bool:
    return domain in _domain_set("free_mail_domains.txt")


def is_disposable(domain: str) -> bool:
    return domain in _domain_set("disposable_domains.txt")


async def check_mx(domain: str, timeout: float) -> bool | None:
    """True when the domain publishes at least one real MX (RFC 7505 null MX counts as False).
    None means the lookup timed out, i.e. unknown."""
    try:
        answer = await dns.asyncresolver.resolve(domain, "MX", lifetime=timeout)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        return False
    except dns.exception.Timeout:
        log.warning("mx lookup timed out", extra={"domain": domain})
        return None
    return any(str(r.exchange).rstrip(".") for r in answer)
