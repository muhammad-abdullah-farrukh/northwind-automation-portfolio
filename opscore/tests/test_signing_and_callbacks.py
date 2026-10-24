import hashlib
import hmac

import pytest

from app.core import signing
from app.core.config import Settings
from app.services import callbacks

SECRET = "s3cret"
BODY = b'{"job_id":"job_1","status":"done"}'


def test_signature_matches_an_independent_computation():
    expected = hmac.new(SECRET.encode(), b"1700000000." + BODY, hashlib.sha256).hexdigest()
    assert signing.sign(SECRET, 1700000000, BODY) == "sha256=" + expected


def test_verify_rejects_tampering_wrong_secret_and_stale_timestamps():
    sig = signing.sign(SECRET, 1700000000, BODY)
    assert signing.verify(SECRET, "1700000000", BODY, sig, now=1700000100)
    assert not signing.verify(SECRET, "1700000000", BODY + b" ", sig, now=1700000100)
    assert not signing.verify("other", "1700000000", BODY, sig, now=1700000100)
    assert not signing.verify(SECRET, "1700000001", BODY, sig, now=1700000100)  # timestamp is signed too
    assert not signing.verify(SECRET, "1700000000", BODY, sig, now=1700000000 + 301)  # replay window
    assert not signing.verify(SECRET, "not-a-number", BODY, sig)


def test_signing_requires_a_secret():
    with pytest.raises(ValueError):
        signing.sign("", 1, BODY)


@pytest.fixture
def settings(monkeypatch):
    table = {
        "host.docker.internal": ["192.168.65.254"],
        "public.example-hooks.com": ["93.184.216.34"],
        "sneaky.example-hooks.com": ["93.184.216.34", "10.1.2.3"],
        "localhost": ["127.0.0.1", "::1"],
    }
    monkeypatch.setattr(callbacks, "_resolve", lambda host: table.get(host, [host]))  # literal IPs resolve to themselves
    return Settings(callback_host_map="localhost:5678->host.docker.internal, n8n.local:443 -> host.docker.internal")


def test_host_map_parsing():
    assert callbacks.parse_host_map(" a:1->b , c:2 -> d ,bad, ->x") == {"a:1": "b", "c:2": "d"}


def test_mapped_internal_host_is_allowed(settings):
    t = callbacks.check_callback_url("https://localhost:5678/webhook-waiting/9?x=1", settings)
    assert (t.host, t.port, t.connect_ip, t.mapped, t.path) == ("localhost", 5678, "192.168.65.254", True, "/webhook-waiting/9?x=1")


def test_public_host_is_allowed_only_if_every_address_is_public(settings):
    assert callbacks.check_callback_url("https://public.example-hooks.com/h", settings).mapped is False
    with pytest.raises(callbacks.CallbackBlocked, match="non-public"):
        callbacks.check_callback_url("https://sneaky.example-hooks.com/h", settings)


@pytest.mark.parametrize("url", ["https://localhost:8000/x", "http://127.0.0.1:5678/x", "gopher://public.example-hooks.com/", "https://u:p@public.example-hooks.com/"])
def test_unmapped_or_odd_urls_are_blocked(settings, url):
    with pytest.raises(callbacks.CallbackBlocked):
        callbacks.check_callback_url(url, settings)
