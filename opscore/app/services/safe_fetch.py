"""Fetch a lead's homepage without letting the URL reach anything internal (SSRF guard).

Rules: http/https on ports 80/443 only; every hop's hostname is resolved here and *all* of its
addresses must be public; the connection then goes to the vetted IP (Host header + TLS SNI keep
the real hostname), so DNS can't be swapped between check and connect. Redirects are followed
manually and re-checked. Body is capped and must be HTML.
"""

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

ALLOWED_PORTS = {"http": 80, "https": 443}
USER_AGENT = "OpsCoreBot/0.1 (+lead enrichment; Northwind Digital demo)"
HTML_TYPES = ("text/html", "application/xhtml+xml")


class BlockedURL(Exception):
    pass


@dataclass
class FetchResult:
    final_url: str
    status_code: int
    text: str


def ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def resolve_public(host: str) -> str:
    """Resolve host and return one address, only if every address it resolves to is public."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if not ip_is_public(literal):
            raise BlockedURL(f"address {host} is not public")
        return host

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedURL(f"cannot resolve {host}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise BlockedURL(f"cannot resolve {host}")
    for addr in addresses:
        if not ip_is_public(ipaddress.ip_address(addr.split("%")[0])):
            raise BlockedURL(f"{host} resolves to non-public address {addr}")
    # Prefer IPv4: Docker Desktop networks rarely route IPv6.
    return sorted(addresses, key=lambda a: ":" in a)[0]


def normalize_site_url(website: str) -> str:
    website = website.strip()
    if "://" not in website:
        website = "https://" + website
    return website


def _check_url(url: str) -> tuple[str, str, int, str]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise BlockedURL(f"scheme {scheme!r} not allowed")
    if not parts.hostname:
        raise BlockedURL("URL has no host")
    port = parts.port or ALLOWED_PORTS[scheme]
    if port != ALLOWED_PORTS[scheme]:
        raise BlockedURL(f"port {port} not allowed")
    if parts.username or parts.password:
        raise BlockedURL("credentials in URL not allowed")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return scheme, parts.hostname.lower(), port, path


async def fetch_homepage(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    max_redirects: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FetchResult:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport) as client:
        for _ in range(max_redirects + 1):
            scheme, host, port, path = _check_url(url)
            ip = await resolve_public(host)
            ip_host = f"[{ip}]" if ":" in ip else ip
            request = client.build_request(
                "GET",
                f"{scheme}://{ip_host}:{port}{path}",
                headers={"Host": host, "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                extensions={"sni_hostname": host},
            )
            response = await client.send(request, stream=True)
            try:
                if response.is_redirect and "location" in response.headers:
                    url = urljoin(url, response.headers["location"])
                    continue
                ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and ctype not in HTML_TYPES:
                    raise BlockedURL(f"content-type {ctype!r} is not HTML")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) >= max_bytes:
                        del body[max_bytes:]
                        break
                encoding = response.encoding or "utf-8"
                return FetchResult(url, response.status_code, body.decode(encoding, errors="replace"))
            finally:
                await response.aclose()
    raise BlockedURL("too many redirects")


def extract_page_text(html: str, max_chars: int) -> str:
    """Title, meta description and visible text — what a person skimming the homepage would read."""
    soup = BeautifulSoup(html, "html.parser")
    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(f"Title: {soup.title.string.strip()}")
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            parts.append(f"Description: {tag['content'].strip()}")
    for tag in soup(["script", "style", "noscript", "svg", "template", "iframe"]):
        tag.decompose()
    body_text = " ".join(soup.get_text(" ").split())
    parts.append(body_text)
    return "\n".join(parts)[:max_chars]
