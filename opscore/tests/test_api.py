from conftest import make_key

CONTRACT_KEYS = [
    "email", "domain", "mx_valid", "is_free_mail", "is_disposable", "website_reachable", "site_summary",
    "industry_guess", "size_band_guess", "rule_score", "enrich_confidence", "cached", "note",
]  # fmt: skip
LEAD = {"email": "Jane.Doe@Acme-Freight.io", "website": "acme-freight.io", "company": "Acme Freight", "name": "Jane Doe"}


def post(client, key, body=LEAD, idem=None):
    headers = {"X-API-Key": key}
    if idem:
        headers["Idempotency-Key"] = idem
    return client.post("/v1/leads/enrich", json=body, headers=headers)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["db"] and r.json()["redis"]


def test_auth_required(client):
    assert client.post("/v1/leads/enrich", json=LEAD).status_code == 401
    assert post(client, "oc_wrong").status_code == 401


def test_enrich_matches_contract(client, api_key, fake_llm):
    r = post(client, api_key, idem="lead-1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == CONTRACT_KEYS
    assert body["email"] == "jane.doe@acme-freight.io" and body["domain"] == "acme-freight.io"
    assert body["mx_valid"] and body["website_reachable"] and not body["is_free_mail"] and not body["cached"]
    assert body["industry_guess"] == "Logistics SaaS" and body["size_band_guess"] == "11-50"
    assert body["rule_score"] == 100
    assert body["enrich_confidence"] == 0.9
    assert body["note"] == "industry and size are LLM guesses"
    assert fake_llm.calls == 1
    assert r.headers.get("Idempotent-Replay") is None


def test_idempotent_replay_returns_stored_response(client, api_key, fake_llm):
    first = post(client, api_key, idem="lead-2")
    second = post(client, api_key, idem="lead-2")
    assert second.status_code == 200
    assert second.content == first.content  # byte-identical, field order included
    assert list(second.json()) == CONTRACT_KEYS
    assert second.headers["Idempotent-Replay"] == "true"
    assert fake_llm.calls == 1


def test_idempotency_key_reuse_with_different_body_is_409(client, api_key):
    assert post(client, api_key, idem="lead-3").status_code == 200
    r = post(client, api_key, body={**LEAD, "email": "someone.else@acme-freight.io"}, idem="lead-3")
    assert r.status_code == 409


def test_idempotency_is_scoped_per_api_key(client, engine, api_key, fake_llm):
    other = make_key(engine, name="other")
    assert post(client, api_key, idem="shared").status_code == 200
    r = post(client, other, idem="shared")
    assert r.status_code == 200 and r.headers.get("Idempotent-Replay") is None


def test_domain_cache_hit_skips_llm(client, api_key, fake_llm):
    post(client, api_key, idem="a")
    r = post(client, api_key, body={**LEAD, "email": "ops@acme-freight.io"}, idem="b")
    assert r.json()["cached"] is True
    assert r.json()["industry_guess"] == "Logistics SaaS"
    assert fake_llm.calls == 1


def test_llm_timeout_degrades_instead_of_failing(client, api_key, fake_llm):
    fake_llm.behaviour = "timeout"
    body = post(client, api_key).json()
    assert body["website_reachable"] is True
    assert body["site_summary"] is None and body["industry_guess"] is None and body["size_band_guess"] is None
    assert "llm unavailable: timeout" in body["note"]
    assert body["enrich_confidence"] == 0.2
    # degraded results are not cached, so the next call tries the LLM again
    fake_llm.behaviour = "ok"
    again = post(client, api_key).json()
    assert again["cached"] is False and again["industry_guess"] == "Logistics SaaS"


def test_invalid_llm_output_degrades(client, api_key, fake_llm):
    fake_llm.behaviour = "invalid"
    body = post(client, api_key).json()
    assert body["industry_guess"] is None
    assert "failed validation" in body["note"]


def test_unreachable_site(client, api_key, fake_llm):
    body = post(client, api_key, body={**LEAD, "website": "down-acme.io"}).json()
    assert body["website_reachable"] is False
    assert "website unreachable" in body["note"]
    assert fake_llm.calls == 0


def test_free_mail_without_website_skips_site(client, api_key, fake_llm):
    body = post(client, api_key, body={"email": "jane.doe@gmail.com"}).json()
    assert body["is_free_mail"] is True and body["website_reachable"] is False
    assert body["rule_score"] == 30
    assert "no company website" in body["note"]
    assert fake_llm.calls == 0


def test_no_mx_and_disposable(client, api_key):
    assert post(client, api_key, body={"email": "x@no-mx-acme.io", "website": "acme-freight.io"}).json()["mx_valid"] is False
    body = post(client, api_key, body={"email": "x@mailinator.com"}).json()
    assert body["is_disposable"] is True and body["rule_score"] <= 5


def test_invalid_email_is_422_and_replayable(client, api_key):
    bad = {"email": "not-an-email"}
    first = post(client, api_key, body=bad, idem="bad-1")
    assert first.status_code == 422
    replay = post(client, api_key, body=bad, idem="bad-1")
    assert replay.status_code == 422 and replay.headers["Idempotent-Replay"] == "true"


def test_rate_limit(client, engine):
    key = make_key(engine, name="tiny", rate_limit=2)
    codes = [post(client, key).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = post(client, key)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0


def test_mx_timeout_is_reported_not_silently_false(client, api_key, monkeypatch):
    from app.services import email_checks

    async def slow_mx(domain, timeout):
        return None

    monkeypatch.setattr(email_checks, "check_mx", slow_mx)
    body = post(client, api_key).json()
    assert body["mx_valid"] is False
    assert "mx lookup timed out" in body["note"]
