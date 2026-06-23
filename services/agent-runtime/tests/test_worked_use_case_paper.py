"""Acceptance test for the paper's §5 worked use case (penalty exposure + delivery risk).

Hermetic (FixtureToolbox), so it runs without the stack. Verifies the cross-system /
penalty / delivery / governance behaviour the paper §5.2 describes.
"""
from __future__ import annotations

import pytest

from app.graph import run_query
from app.tools.fixtures import FixtureToolbox

PAPER_QUERY = (
    "Which Q3 supplier contracts have penalty-clause exposure greater than one million "
    "dollars, and which of those suppliers have at-risk delivery performance based on the "
    "last six months of operational telemetry?")

PRINCIPAL = {"user": "demo-analyst", "purpose": "supplier_risk_review",
             "org_access": ["*"], "clearance": []}


@pytest.fixture(scope="module")
def result():
    return run_query(PAPER_QUERY, FixtureToolbox(), PRINCIPAL)


def test_intent_is_penalty_delivery(result):
    intent = next(e["output"]["intent"] for e in result["events"] if e["action"] == "parse_intent")
    assert intent["scenario"] == "penalty_delivery"
    assert intent["quarter"] == "FY26-Q3"
    assert intent["penalty_exposure_min"] == 1_000_000
    assert intent["delivery_at_risk"] is True


def test_at_risk_eu_high_exposure_suppliers_shown(result):
    # Q3, exposure > $1M, at-risk delivery, AND EU-resident → SUP-009..012
    assert {r["supplier_id"] for r in result["filtered"]["allowed"]} == {f"SUP-0{i:02d}" for i in range(9, 13)}


def test_non_eu_supplier_excluded_by_residency(result):
    residency = {r["supplier_id"] for r in result["filtered"]["excluded"]
                 if r["excluded_by"] == "require_residency_match"}
    assert residency == {"SUP-013"}  # at-risk + high-exposure but data hosted in the US


def test_exposed_but_not_at_risk_flagged(result):
    delivery = {r["supplier_id"] for r in result["filtered"]["excluded"]
                if r["excluded_by"] == "delivery_within_tolerance"}
    assert delivery == {"SUP-014", "SUP-015"}


def test_commercial_terms_redacted(result):
    redacted = {r["supplier_id"] for r in result["filtered"]["allowed"]
                if any(x["policy"] == "redact_commercial_terms" for x in r["redactions"])}
    assert redacted == {"SUP-011", "SUP-012"}


def test_five_of_seven_policies_exercised(result):
    # precheck + per-row policies across the pipeline
    policies = {d.get("policy") for e in result["events"] for d in e.get("policy_decisions", [])}
    assert {"allow_supplier_query", "require_residency_match", "redact_commercial_terms",
            "mask_supplier_contact_pii", "audit_required_on_decline"} <= policies


def test_supplier_contact_pii_masked_for_all_shown(result):
    for r in result["filtered"]["allowed"]:
        assert any(x["policy"] == "mask_supplier_contact_pii" for x in r["redactions"])


def test_cross_system_identity_resolution_present(result):
    for r in result["filtered"]["allowed"]:
        systems = {ref.split(":")[0] for ref in r.get("system_refs", [])}
        assert {"ERP", "MES", "CMS"} <= systems


def test_answer_has_markers_and_exposure(result):
    ans = result["answer"]
    assert "[redacted: policy redact_commercial_terms]" in ans
    assert "[redacted: policy mask_supplier_contact_pii]" in ans
    assert "penalty exposure" in ans.lower()


def test_ge_two_mask_decisions(result):
    assert sum(1 for d in result["decisions"] if d.get("outcome") == "mask") >= 2


def test_regulatory_mapping_includes_oversight(result):
    arts = {a for e in result["events"] for a in e["regulatory_mapping"]["eu_ai_act_articles"]}
    assert {"12", "13", "14"} <= arts  # record-keeping, transparency, human oversight (§5.3)
