import pytest
from conftest import make_key
from fpdf import FPDF

from app.models.invoice import INVOICE_FIELDS
from app.services.llm import LLMError
from evals.generate_invoices import build

CONTRACT_KEYS = ["job_id", "status", "duplicate_of", "data", "confidence", "validation", "meta"]
DATA_KEYS = ["vendor", "invoice_no", "invoice_date", "due_date", "currency", "subtotal", "tax", "total", "line_items"]
META_KEYS = ["model", "prompt_version", "tokens", "cost_usd", "latency_ms"]


def llm_out(data: dict, conf: float = 0.95, **overrides) -> dict:
    return {**data, **overrides, "field_confidence": {f: conf for f in INVOICE_FIELDS}}


def upload(client, key, content, *, name="invoice.pdf", idem=None, schema="invoice", ctype="application/pdf"):
    headers = {"X-API-Key": key}
    if idem:
        headers["Idempotency-Key"] = idem
    return client.post("/v1/extract/sync", files={"file": (name, content, ctype)}, data={"schema": schema}, headers=headers)


@pytest.fixture(scope="module")
def samples():
    return {i: build(i) for i in (1, 2, 3, 5)}


def test_clean_invoice_is_done_and_matches_contract(client, api_key, fake_llm, samples):
    content, label = samples[1]
    fake_llm.queue = [llm_out(label["data"])]
    r = upload(client, api_key, content)
    assert r.status_code == 200, r.text
    body = r.json()
    assert list(body) == CONTRACT_KEYS
    assert list(body["data"]) == DATA_KEYS and list(body["meta"]) == META_KEYS
    assert body["job_id"].startswith("job_") and len(body["job_id"]) == 30
    assert body["status"] == "done" and body["duplicate_of"] is None
    assert body["validation"] == {"ok": True, "errors": []}
    assert body["data"] == label["data"]
    assert body["confidence"]["overall"] >= 0.85
    assert set(body["confidence"]["fields"]) == set(INVOICE_FIELDS)
    assert body["meta"] == {"model": "fake-extract", "prompt_version": "invoice_extract_v2", "tokens": 1200, "cost_usd": None, "latency_ms": 7}
    assert fake_llm.calls == 1
    assert "<invoice_text>" in fake_llm.last_kwargs["user"]


def test_repair_pass_fixes_a_misread_total(client, api_key, fake_llm, samples):
    content, label = samples[2]
    misread = llm_out(label["data"], total=label["data"]["total"] + 100)
    fake_llm.queue = [misread, llm_out(label["data"])]
    body = upload(client, api_key, content).json()
    assert body["status"] == "done" and body["data"]["total"] == label["data"]["total"]
    assert fake_llm.calls == 2
    assert "total_mismatch" in fake_llm.last_kwargs["user"] or "subtotal + tax" in fake_llm.last_kwargs["user"]
    assert body["meta"]["tokens"] == 2400


def test_invoice_that_does_not_add_up_goes_to_review_with_printed_values(client, api_key, fake_llm, samples):
    content, label = samples[5]
    assert "bad_totals" in label["flags"]
    fake_llm.queue = [llm_out(label["data"]), llm_out(label["data"])]  # model keeps reporting what is printed
    body = upload(client, api_key, content).json()
    assert body["status"] == "needs_review"
    assert body["validation"]["ok"] is False
    assert {e["code"] for e in body["validation"]["errors"]} == {"total_mismatch"}
    assert body["data"]["total"] == label["data"]["total"]  # not "fixed"
    assert body["confidence"]["fields"]["total"] <= 0.5
    assert fake_llm.calls == 2


def test_unparseable_output_twice_fails(client, api_key, fake_llm, samples):
    content, _ = samples[1]
    fake_llm.queue = [{"vendor": "x"}, {"nonsense": True}]
    body = upload(client, api_key, content).json()
    assert body["status"] == "failed" and body["data"] is None
    assert body["validation"]["errors"] and all(e["code"] == "schema_error" for e in body["validation"]["errors"])


def test_value_not_found_in_document_lowers_confidence(client, api_key, fake_llm, samples):
    content, label = samples[3]
    fake_llm.queue = [llm_out(label["data"], vendor="Totally Different Trading Ltd")]  # passes arithmetic, not grounded
    body = upload(client, api_key, content).json()
    assert body["validation"]["ok"] is True
    assert body["status"] == "needs_review"
    assert body["confidence"]["fields"]["vendor"] < 0.5 and body["confidence"]["overall"] < 0.85


def test_duplicate_invoice_points_to_first_job(client, api_key, fake_llm, samples):
    content, label = samples[1]
    fake_llm.queue = [llm_out(label["data"]), llm_out(label["data"])]
    first = upload(client, api_key, content, idem="dup-a").json()
    second = upload(client, api_key, content, idem="dup-b").json()
    assert first["duplicate_of"] is None
    assert second["duplicate_of"] == first["job_id"] and second["job_id"] != first["job_id"]


def test_duplicates_are_not_matched_across_clients(client, engine, api_key, fake_llm, samples):
    content, label = samples[1]
    other_client = make_key(engine, name="other-client")
    fake_llm.queue = [llm_out(label["data"]), llm_out(label["data"])]
    upload(client, api_key, content)
    second = upload(client, other_client, content).json()
    assert second["duplicate_of"] is None  # another client's invoice must not be revealed


def test_llm_unavailable_is_503_and_key_is_released(client, api_key, fake_llm, samples):
    content, label = samples[1]
    fake_llm.queue = [LLMError("LLM disabled (LLM_PROVIDER=none)")]
    r = upload(client, api_key, content, idem="retry-me")
    assert r.status_code == 503 and r.headers["Retry-After"] == "30"
    fake_llm.queue = [llm_out(label["data"])]
    assert upload(client, api_key, content, idem="retry-me").status_code == 200


def test_idempotent_replay_returns_same_job(client, api_key, fake_llm, samples):
    content, label = samples[2]
    fake_llm.queue = [llm_out(label["data"])]
    first = upload(client, api_key, content, idem="same")
    second = upload(client, api_key, content, idem="same")
    assert second.content == first.content and second.headers["Idempotent-Replay"] == "true"
    assert fake_llm.calls == 1
    other_content, _ = samples[3]
    assert upload(client, api_key, other_content, idem="same").status_code == 409


def test_rejects_non_pdf_unknown_schema_and_scanned_pdf(client, api_key, fake_llm, samples):
    r = upload(client, api_key, b"\x89PNG\r\n\x1a\n" + b"0" * 100, name="scan.png", ctype="image/png")
    assert r.status_code == 415 and "OCR" in r.json()["detail"]
    assert upload(client, api_key, samples[1][0], schema="receipt").status_code == 422

    pdf = FPDF()
    pdf.add_page()
    body = upload(client, api_key, bytes(pdf.output())).json()
    assert body["status"] == "failed" and body["validation"]["errors"][0]["code"] == "no_text_layer"
    assert fake_llm.calls == 0


def test_extraction_needs_an_api_key(client, engine, samples):
    assert client.post("/v1/extract/sync", files={"file": ("a.pdf", samples[1][0], "application/pdf")}).status_code == 401
    assert make_key(engine, name="second")  # keys are independent; covered further in test_api
