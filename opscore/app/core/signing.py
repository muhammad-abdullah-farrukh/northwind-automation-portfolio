"""HMAC-SHA256 signatures for outgoing callbacks (brief §4.3 step 7).

Signed message = f"{timestamp}.".encode() + raw_body. The timestamp is sent separately in
X-OpsCore-Timestamp so a receiver can reject stale replays; the signature covers both, so
neither can be swapped. (Named signing.py rather than hmac.py to avoid shadowing the stdlib.)
"""

import hashlib
import hmac
import time

SIGNATURE_HEADER = "X-OpsCore-Signature"
TIMESTAMP_HEADER = "X-OpsCore-Timestamp"
PREFIX = "sha256="


def sign(secret: str, timestamp: int, body: bytes) -> str:
    if not secret:
        raise ValueError("CALLBACK_HMAC_SECRET is not set")
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return PREFIX + digest


def verify(secret: str, timestamp: str | int, body: bytes, signature: str, *, tolerance_s: int = 300, now: float | None = None) -> bool:
    """Reference verifier (what a receiver such as n8n must do): constant-time compare + freshness."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - ts) > tolerance_s:
        return False
    return hmac.compare_digest(sign(secret, ts, body), signature or "")
