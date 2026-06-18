"""End-to-end worked use case against the *live* stack (Neo4j + OPA + Cube + feedback).

Opt-in: set VCL_LIVE=1 after `docker compose up`. Proves the real components produce the
same governed outcome as the fixtures. [spec §6 acceptance]
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VCL_LIVE") != "1",
                                reason="set VCL_LIVE=1 with the stack running")

WORKED_QUERY = (
    "Show me the top five suppliers in EMEA with contracts expiring before December 2026, "
    "where the contracts contain PII clauses. Only include suppliers whose data subjects "
    "have valid GDPR consent."
)
PRINCIPAL = {"user": "demo-analyst", "purpose": "supplier_risk_review",
             "org_access": ["EMEA", "AMER", "APAC"]}


@pytest.fixture(scope="module")
def live_result():
    from app.graph import run_query
    from app.tools.live import LiveToolbox
    tb = LiveToolbox()
    try:
        return run_query(WORKED_QUERY, tb, PRINCIPAL)
    finally:
        tb.close()


def test_live_outcomes_match_worked_case(live_result):
    f = live_result["filtered"]
    assert {r["supplier_id"] for r in f["allowed"]} == {f"SUP-00{i}" for i in range(1, 6)}
    assert {r["supplier_id"] for r in f["masked"]} == {"SUP-006", "SUP-007"}
    assert {r["supplier_id"] for r in f["excluded"]} == {"SUP-008"}


def test_live_trace_persisted(live_result):
    import httpx
    url = os.environ.get("VCL_FEEDBACK_URL", "http://localhost:8200")
    r = httpx.get(f"{url}/trace/{live_result['trace_id']}", timeout=10.0)
    assert r.status_code == 200
    assert r.json()["event_count"] >= 7
