"""Python policy test client — hits the live OPA REST API with allow & deny cases
for each of the five VCL policies. [spec §5.3, Phase 3]

Run the policy engine first:  docker compose up -d policy-engine
Then:                         uv run pytest services/policy-engine/tests -q

Skips (rather than fails) if OPA is not reachable, so the full suite stays green
without the stack running; CI starts OPA explicitly.
"""
from __future__ import annotations

import os

import httpx
import pytest

OPA_URL = os.environ.get("VCL_POLICY_URL", "http://localhost:8181")
AS_OF = "2026-06-18"


def _decide(rule: str, inp: dict) -> dict:
    try:
        r = httpx.post(f"{OPA_URL}/v1/data/vcl/{rule}", json={"input": inp}, timeout=5.0)
    except httpx.HTTPError:
        pytest.skip(f"OPA not reachable at {OPA_URL}; start `docker compose up -d policy-engine`")
    r.raise_for_status()
    return r.json().get("result", {})


# 1. allow_supplier_query -------------------------------------------------------
def test_supplier_query_allow():
    d = _decide("allow_supplier_query",
                {"principal": {"org_access": ["EMEA"]}, "resource": {"geo": "EMEA"}})
    assert d["allow"] is True
    assert d["outcome"] == "allow"


def test_supplier_query_deny():
    d = _decide("allow_supplier_query",
                {"principal": {"org_access": ["EMEA"]}, "resource": {"geo": "AMER"}})
    assert d["allow"] is False
    assert d["outcome"] == "deny"
    assert d["reasons"]


# 2. allow_pii_field_access -----------------------------------------------------
def test_pii_allow():
    d = _decide("allow_pii_field_access", {
        "as_of": AS_OF,
        "principal": {"purpose": "supplier_risk_review"},
        "resource": {"consent_retention_until": "2027-03-31"},
    })
    assert d["outcome"] == "allow"


def test_pii_mask_when_consent_expired():
    d = _decide("allow_pii_field_access", {
        "as_of": AS_OF,
        "principal": {"purpose": "supplier_risk_review"},
        "resource": {"consent_retention_until": "2026-03-26"},
    })
    assert d["outcome"] == "mask"
    assert d["allow"] is False


def test_pii_deny_without_purpose():
    d = _decide("allow_pii_field_access", {
        "as_of": AS_OF,
        "principal": {"purpose": ""},
        "resource": {"consent_retention_until": "2027-03-31"},
    })
    assert d["outcome"] == "deny"


# 3. require_residency_match ----------------------------------------------------
def test_residency_allow_eu():
    d = _decide("require_residency_match",
                {"context": {"residency_scope": "EU"}, "resource": {"data_residency": "EU"}})
    assert d["allow"] is True


def test_residency_deny_us_for_eu_query():
    d = _decide("require_residency_match",
                {"context": {"residency_scope": "EU"}, "resource": {"data_residency": "US"}})
    assert d["allow"] is False
    assert d["outcome"] == "deny"


# 4. mask_secrets_in_response ---------------------------------------------------
def test_secrets_masked():
    d = _decide("mask_secrets_in_response", {"resource": {"contains_secrets": True}})
    assert d["outcome"] == "mask"


def test_secrets_allowed():
    d = _decide("mask_secrets_in_response", {"resource": {"contains_secrets": False}})
    assert d["outcome"] == "allow"


# 5. audit_required_on_decline --------------------------------------------------
@pytest.mark.parametrize("outcome,expected", [("deny", True), ("mask", True), ("allow", False)])
def test_audit_required(outcome, expected):
    d = _decide("audit_required_on_decline", {"decision": {"outcome": outcome}})
    assert d["audit_required"] is expected
