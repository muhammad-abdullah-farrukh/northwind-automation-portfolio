"""Signed callbacks to the URL a client gave in POST /v1/jobs (e.g. n8n's Wait-node resume URL).

Callback URLs come from authenticated clients but still point our server at arbitrary hosts,
so they get the same SSRF treatment as homepage fetches (DECISIONS D26):
- public hosts: every resolved address must be public; the connection goes to the vetted IP.
- non-public hosts: only via an explicit CALLBACK_HOST_MAP entry ("localhost:5678->host.docker.internal").
  The connection goes to the mapped target while Host header and TLS SNI keep the original name,
  so a pinned self-signed certificate (CALLBACK_CA_FILE) for "localhost" still verifies.
TLS verification is never switched off.
"""

import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core import signing
from app.core.config import Settings
from app.services.safe_fetch import ip_is_public

DEFAULT_PORTS = {"http": 80, "https": 443}

# Tests swap this for an httpx.MockTransport.
TRANSPORT: httpx.BaseTransport | None = None


class CallbackBlocked(ValueError):
    pass


@dataclass
class Target:
    scheme: str
    host: str  # name the client used (Host header, SNI, cert check)
    port: int
    path: str
    connect_ip: str
    mapped: bool


def parse_host_map(raw: str) -> dict[str, str]:
    pairs = {}
    for item in (raw or "").split(","):
        if "->" in item:
            source, target = (part.strip().lower() for part in item.split("->", 1))
            if source and target:
                pairs[source] = target
    return pairs


def _resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}, key=lambda a: ":" in a)
    except socket.gaierror as exc:
        raise CallbackBlocked(f"cannot resolve {host}") from exc


def check_callback_url(url: str, settings: Settings) -> Target:
    """Raise CallbackBlocked unless the URL is allowed; return where to connect."""
    parts = urlsplit(url or "")
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS:
        raise CallbackBlocked("callback_url must be http or https")
    if not parts.hostname:
        raise CallbackBlocked("callback_url has no host")
    if parts.username or parts.password:
        raise CallbackBlocked("credentials in callback_url are not allowed")
    host = parts.hostname.lower()
    port = parts.port or DEFAULT_PORTS[scheme]
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")

    mapped_to = parse_host_map(settings.callback_host_map).get(f"{host}:{port}")
    if mapped_to:
        return Target(scheme, host, port, path, _resolve(mapped_to)[0], mapped=True)

    addresses = _resolve(host)
    for addr in addresses:
        if not ip_is_public(ipaddress.ip_address(addr.split("%")[0])):
            raise CallbackBlocked(f"{host} resolves to non-public address {addr}; add it to CALLBACK_HOST_MAP to allow it")
    return Target(scheme, host, port, path, addresses[0], mapped=False)


@dataclass
class DeliveryResult:
    status_code: int | None
    latency_ms: int
    error: str | None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300

    @property
    def permanent(self) -> bool:
        # A 4xx means the receiver understood and refused (e.g. n8n's 409 once a Wait execution has finished);
        # retrying can't change that. 408/425/429 are the 4xx codes that do mean "try again later".
        return self.status_code is not None and 400 <= self.status_code < 500 and self.status_code not in (408, 425, 429)


def _verify_context(target: Target, settings: Settings) -> ssl.SSLContext | bool:
    if target.scheme != "https":
        return True
    if target.mapped and settings.callback_ca_file:
        return ssl.create_default_context(cafile=settings.callback_ca_file)
    return True  # system CAs


def deliver(url: str, body: bytes, *, job_id: str, settings: Settings, now: int | None = None) -> DeliveryResult:
    """One signed POST. Never raises for network/HTTP errors; the caller decides about retries."""
    target = check_callback_url(url, settings)
    timestamp = now if now is not None else int(time.time())
    ip_host = f"[{target.connect_ip}]" if ":" in target.connect_ip else target.connect_ip
    headers = {
        "Content-Type": "application/json",
        "Host": target.host if target.port == DEFAULT_PORTS[target.scheme] else f"{target.host}:{target.port}",
        signing.TIMESTAMP_HEADER: str(timestamp),
        signing.SIGNATURE_HEADER: signing.sign(settings.callback_hmac_secret.get_secret_value(), timestamp, body),
        "X-OpsCore-Job-Id": job_id,
        "User-Agent": "OpsCore-Callback/0.1",
    }
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=settings.callback_timeout_s, verify=_verify_context(target, settings), transport=TRANSPORT) as client:
            request = client.build_request(
                "POST",
                f"{target.scheme}://{ip_host}:{target.port}{target.path}",
                content=body,
                headers=headers,
                extensions={"sni_hostname": target.host},
            )
            response = client.send(request)
        return DeliveryResult(response.status_code, int((time.perf_counter() - started) * 1000), None if response.is_success else response.text[:300])
    except httpx.HTTPError as exc:
        return DeliveryResult(None, int((time.perf_counter() - started) * 1000), f"{type(exc).__name__}: {exc}"[:300])
