import ipaddress

import httpx
import pytest

from app.services import safe_fetch
from app.services.safe_fetch import BlockedURL

PUBLIC_IP = "93.184.216.34"


@pytest.mark.parametrize(
    ("addr", "public"),
    [
        ("8.8.8.8", True),
        (PUBLIC_IP, True),
        ("127.0.0.1", False),
        ("10.0.0.5", False),
        ("172.16.3.4", False),
        ("192.168.1.10", False),
        ("169.254.169.254", False),  # cloud metadata
        ("100.64.0.1", False),  # carrier-grade NAT
        ("0.0.0.0", False),
        ("::1", False),
        ("fd00::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
        ("2606:4700:4700::1111", True),
    ],
)
def test_ip_is_public(addr, public):
    assert safe_fetch.ip_is_public(ipaddress.ip_address(addr)) is public


async def test_resolve_blocks_literal_private_ip():
    with pytest.raises(BlockedURL):
        await safe_fetch.resolve_public("127.0.0.1")


async def test_resolve_blocks_hostname_pointing_inside():
    with pytest.raises(BlockedURL):
        await safe_fetch.resolve_public("localhost")


@pytest.mark.parametrize(
    "url",
    ["ftp://acme.io/", "file:///etc/passwd", "http://acme.io:8080/", "https://acme.io:22/", "https://user:pw@acme.io/", "http:///nohost"],
)
async def test_disallowed_urls(url):
    with pytest.raises(BlockedURL):
        await safe_fetch.fetch_homepage(url, timeout=1, max_bytes=1000)


@pytest.fixture
def fake_dns(monkeypatch):
    table = {"acme-freight.io": PUBLIC_IP, "internal.acme-freight.io": "10.0.0.5"}

    async def resolve(host: str) -> str:
        ip = table[host]
        if not safe_fetch.ip_is_public(ipaddress.ip_address(ip)):
            raise BlockedURL(f"{host} resolves to non-public address {ip}")
        return ip

    monkeypatch.setattr(safe_fetch, "resolve_public", resolve)


async def test_connects_to_vetted_ip_with_original_host_and_sni(fake_dns):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"], seen["header"], seen["sni"] = request.url.host, request.headers["host"], request.extensions.get("sni_hostname")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html>hi</html>")

    res = await safe_fetch.fetch_homepage("https://acme-freight.io/", timeout=1, max_bytes=1000, transport=httpx.MockTransport(handler))
    assert res.status_code == 200 and "hi" in res.text
    assert seen == {"host": PUBLIC_IP, "header": "acme-freight.io", "sni": "acme-freight.io"}


async def test_redirect_to_private_address_is_blocked(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://internal.acme-freight.io/admin"})

    with pytest.raises(BlockedURL, match="non-public"):
        await safe_fetch.fetch_homepage("https://acme-freight.io/", timeout=1, max_bytes=1000, transport=httpx.MockTransport(handler))


async def test_redirect_loop_is_bounded(fake_dns):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"location": "https://acme-freight.io/again"})

    with pytest.raises(BlockedURL, match="too many redirects"):
        await safe_fetch.fetch_homepage(
            "https://acme-freight.io/", timeout=1, max_bytes=1000, max_redirects=2, transport=httpx.MockTransport(handler)
        )


async def test_body_is_capped_and_non_html_rejected(fake_dns):
    def big(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text="x" * 50_000)

    res = await safe_fetch.fetch_homepage("https://acme-freight.io/", timeout=1, max_bytes=1000, transport=httpx.MockTransport(big))
    assert len(res.text) == 1000

    def pdf(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    with pytest.raises(BlockedURL, match="not HTML"):
        await safe_fetch.fetch_homepage("https://acme-freight.io/", timeout=1, max_bytes=1000, transport=httpx.MockTransport(pdf))


def test_extract_page_text_keeps_title_and_description_drops_scripts():
    html = '<html><head><title>Acme</title><meta name="description" content="Fleet software"><script>evil()</script></head><body><p>Hello  world</p></body></html>'
    text = safe_fetch.extract_page_text(html, 500)
    assert "Title: Acme" in text and "Description: Fleet software" in text and "Hello world" in text
    assert "evil" not in text
