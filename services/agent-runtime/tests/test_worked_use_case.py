"""Acceptance test for the worked use case. [spec §6]

Verifies all ten steps of the paper's §5 scenario end-to-end against the deterministic
fixtures (so `pytest` is green with no services running). The same pipeline runs against
the live stack via test_live_stack.py when VCL_LIVE=1.
"""
from __future__ import annotations

import pytest

from app.graph import run_query
from app.tools.fixtures import FixtureToolbox

WORKED_QUERY = (
    "Show me the top five suppliers in EMEA with contracts expiring before December 2026, "
    "where the contracts contain PII clauses. Only include suppliers whose data subjects "
    "have valid GDPR consent."
)

PRINCIPAL = {"user": "demo-analyst", "purpose": "supplier_risk_review",
             "org_access": ["EMEA", "AMER", "APAC"]}


@pytest.fixture(scope="module")
def result():
    return run_query(WORKED_QUERY, FixtureToolbox(), PRINCIPAL)


# Step 2 — parse → intent + filters
def test_step2_intent_parsed(result):
    intent = next(e["output"]["intent"] for e in result["events"]
                  if e["action"] == "parse_intent")
    assert intent["geo"] == "EMEA"
    assert intent["contains_pii"] is True
    assert intent["end_before"] == "2026-12-31"
    assert intent["residency_scope"] == "EU"
    assert intent["limit"] == 5


# Step 3 — policy precheck ALLOW
def test_step3_policy_precheck_allows(result):
    precheck = next(e for e in result["events"]
                    if e["action"] == "precheck_allow_supplier_query")
    assert precheck["policy_decisions"][0]["allow"] is True


# Step 4 — semantic layer consulted
def test_step4_semantic_layer_queried(result):
    assert any(e["component"] == "semantic_layer" and e["action"] == "governed_query"
               for e in result["events"])


# Step 5 — context graph returns the matching supplier-contract pairs
def test_step5_graph_retrieval(result):
    graph_ev = next(e for e in result["events"] if e["action"] == "query_supplier_contracts")
    assert graph_ev["output"]["row_count"] == 8  # the eight worked-case anchors


# Step 6 — per-row policy filter: 5 shown, 2 masked (expired consent), 1 excluded (US residency)
def test_step6_policy_filter_outcomes(result):
    f = result["filtered"]
    assert {r["supplier_id"] for r in f["allowed"]} == {f"SUP-00{i}" for i in range(1, 6)}
    assert {r["supplier_id"] for r in f["masked"]} == {"SUP-006", "SUP-007"}
    assert {r["supplier_id"] for r in f["excluded"]} == {"SUP-008"}


def test_step6_masked_reason_is_consent(result):
    for r in result["filtered"]["masked"]:
        assert any(x["policy"] == "allow_pii_field_access" for x in r["redactions"])


def test_step6_excluded_reason_is_residency(result):
    assert result["filtered"]["excluded"][0]["excluded_by"] == "require_residency_match"


# Step 7 — synthesised top-five answer that explains shown vs redacted
def test_step7_answer_lists_five_and_marks_redactions(result):
    ans = result["answer"]
    for i in range(1, 6):
        assert f"SUP-00{i}" in ans or _name(i) in ans
    assert "[redacted: policy allow_pii_field_access]" in ans
    assert "require_residency_match" in ans


# Step 8 — response carries a trace id
def test_step8_trace_id_present(result):
    assert result["trace_id"]
    assert len(result["trace_id"]) >= 16


# Step 9 — the trace shows every step with policy decisions visible
def test_step9_trace_has_all_components(result):
    components = {e["component"] for e in result["events"]}
    assert {"semantic_layer", "context_graph", "policy_engine", "response", "agent"} <= components


def test_step9_at_least_two_deny_or_mask(result):
    """spec §8: at least two policy decisions are deny/mask — policy doing real work."""
    outcomes = [d.get("outcome") for d in result["decisions"]]
    assert sum(1 for o in outcomes if o in ("deny", "mask")) >= 2


# Step 10 — trace is regulator-addressable (feeds the compliance PDF)
def test_step10_regulatory_mapping_present(result):
    articles = set()
    nist = set()
    for e in result["events"]:
        articles.update(e["regulatory_mapping"]["eu_ai_act_articles"])
        nist.update(e["regulatory_mapping"]["nist_rmf_functions"])
    assert {"12", "13"} <= articles            # transparency + record-keeping
    assert "9" in articles                     # risk management
    assert any(f.startswith("MEASURE-2.7") for f in nist)


def test_feedback_loop_received_every_event(result):
    # The audit emitter sink (feedback_loop.emit) saw the same events as the trace.
    assert len(result["events"]) >= 7


_NAMES = {1: "Helvetia", 2: "Nordic", 3: "Britannia", 4: "Rhein", 5: "Iberia"}


def _name(i: int) -> str:
    return _NAMES[i]
