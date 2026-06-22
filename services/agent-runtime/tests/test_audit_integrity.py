"""Live tamper-evidence test against the running feedback loop. [paper §6.1]

Posts a trace, confirms /verify reports it intact, then edits a row directly in the SQLite
file and confirms /verify now flags the break. Skips if the feedback loop isn't reachable.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import httpx
import pytest

FEEDBACK_URL = os.environ.get("VCL_FEEDBACK_URL", "http://localhost:8200")
DB_PATH = Path(__file__).resolve().parents[3] / "data" / "audit.sqlite"


def _reachable() -> bool:
    try:
        return httpx.get(f"{FEEDBACK_URL}/healthz", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="feedback loop not running")


def _event(trace_id, step, action):
    return {"trace_id": trace_id, "step_id": f"{trace_id}-{step}",
            "timestamp": f"2026-06-21T00:00:0{step}Z", "component": "agent",
            "action": action, "principal": {"user": "test"}, "input": {}, "output": {"step": step},
            "policy_decisions": [], "regulatory_mapping": {"eu_ai_act_articles": ["12"],
                                                           "nist_rmf_functions": ["MEASURE-2.7"]}}


def test_chain_valid_then_detects_tamper():
    trace_id = f"test-integrity-{uuid.uuid4()}"  # unique per run → idempotent
    for i in range(1, 4):
        httpx.post(f"{FEEDBACK_URL}/events", json=_event(trace_id, i, f"step{i}"), timeout=5)

    assert httpx.get(f"{FEEDBACK_URL}/verify/{trace_id}", timeout=5).json()["valid"] is True

    if not DB_PATH.exists():
        pytest.skip("audit.sqlite not on this host (feedback loop uses a different volume)")
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE trace_events SET payload = ? WHERE trace_id = ? AND "
                "row_id = (SELECT MIN(row_id) FROM trace_events WHERE trace_id = ?)",
                ('{"tampered":true}', trace_id, trace_id))
    con.commit()
    con.close()

    after = httpx.get(f"{FEEDBACK_URL}/verify/{trace_id}", timeout=5).json()
    assert after["valid"] is False
    assert after["broken_at_step"] == 1
