"""Sortable ids: `job_` + ULID (48-bit ms timestamp + 80 random bits, Crockford base32)."""

import secrets
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        value, rem = divmod(value, 32)
        chars.append(_CROCKFORD[rem])
    return "".join(reversed(chars))


def new_job_id() -> str:
    return f"job_{ulid()}"
