"""Guards against drift between the Python policy mirror (FixtureToolbox._decide) and the
real OPA service. Runs only when OPA is reachable. [DECISIONS D1]
"""
from __future__ import annotations

import os

import httpx
import pytest

from app.tools.fixtures import FixtureToolbox

OPA_URL = os.environ.get("VCL_POLICY_URL", "http://localhost:8181")

CASES = [
    ("allow_supplier_query", {"principal": {"org_access": ["EMEA"]}, "resource": {"geo": "EMEA"}}),
    ("allow_supplier_query", {"principal": {"org_access": ["EMEA"]}, "resource": {"geo": "AMER"}}),
    ("allow_pii_field_access", {"as_of": "2026-06-18", "principal": {"purpose": "supplier_risk_review"},
                               "resource": {"consent_retention_until": "2027-03-31"}}),
    ("allow_pii_field_access", {"as_of": "2026-06-18", "principal": {"purpose": "supplier_risk_review"},
                               "resource": {"consent_retention_until": "2026-03-26"}}),
    ("allow_pii_field_access", {"as_of": "2026-06-18", "principal": {"purpose": ""},
                               "resource": {"consent_retention_until": "2027-03-31"}}),
    ("require_residency_match", {"context": {"residency_scope": "EU"}, "resource": {"data_residency": "EU"}}),
    ("require_residency_match", {"context": {"residency_scope": "EU"}, "resource": {"data_residency": "US"}}),
    ("require_residency_match", {"context": {"residency_scope": "GLOBAL"}, "resource": {"data_residency": "US"}}),
    ("mask_secrets_in_response", {"resource": {"contains_secrets": True}}),
    ("mask_secrets_in_response", {"resource": {"contains_secrets": False}}),
    ("audit_required_on_decline", {"decision": {"outcome": "deny"}}),
    ("audit_required_on_decline", {"decision": {"outcome": "allow"}}),
    ("redact_commercial_terms", {"principal": {"clearance": []}, "resource": {"commercial_confidential": True}}),
    ("redact_commercial_terms", {"principal": {"clearance": ["contract_detail"]}, "resource": {"commercial_confidential": True}}),
    ("redact_commercial_terms", {"principal": {"clearance": []}, "resource": {"commercial_confidential": False}}),
    ("mask_supplier_contact_pii", {"resource": {"has_contact_pii": True}}),
    ("mask_supplier_contact_pii", {"resource": {"has_contact_pii": False}}),
]


def _opa(rule: str, payload: dict) -> dict:
    try:
        r = httpx.post(f"{OPA_URL}/v1/data/vcl/{rule}", json={"input": payload}, timeout=5.0)
    except httpx.HTTPError:
        pytest.skip(f"OPA not reachable at {OPA_URL}")
    r.raise_for_status()
    return r.json().get("result", {})


@pytest.mark.parametrize("rule,payload", CASES)
def test_mirror_matches_opa(rule, payload):
    fx = FixtureToolbox()
    mirror = fx._decide(rule, payload)
    live = _opa(rule, payload)
    # Compare the decision-driving fields (reasons text is allowed to match too).
    for key in ("outcome", "allow", "audit_required"):
        if key in live or key in mirror:
            assert mirror.get(key) == live.get(key), f"{rule} {key}: mirror={mirror} opa={live}"
