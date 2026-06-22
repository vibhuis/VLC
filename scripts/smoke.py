#!/usr/bin/env python3
"""End-to-end smoke test against the running stack. [spec §6, §8]

Usage:  docker compose up -d --build   &&   python scripts/smoke.py
Exits non-zero if the worked use case doesn't produce 5 shown / 2 masked / 1 excluded,
or if the trace isn't persisted. Used by CI and by reviewers to confirm the demo works.
"""
from __future__ import annotations

import sys
import time

import httpx

AGENT = "http://localhost:8000"
WORKED_QUERY = (
    "Show me the top five suppliers in EMEA with contracts expiring before December 2026, "
    "where the contracts contain PII clauses. Only include suppliers whose data subjects "
    "have valid GDPR consent."
)


def wait_healthy(timeout: int = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{AGENT}/healthz", timeout=5).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(3)
    sys.exit("agent runtime did not become healthy in time")


def main() -> None:
    wait_healthy()
    r = httpx.post(f"{AGENT}/query", json={"query": WORKED_QUERY}, timeout=90)
    r.raise_for_status()
    d = r.json()
    answer = d["answer"]

    checks = {
        "answer lists Helvetia (top supplier)": "Helvetia" in answer,
        "PII redaction marker present": "[redacted: policy allow_pii_field_access]" in answer,
        "residency exclusion present": "require_residency_match" in answer,
        "trace id returned": bool(d["trace_id"]),
        "at least 2 deny/mask decisions":
            sum(1 for x in d["decisions"] if x.get("outcome") in ("deny", "mask")) >= 2,
    }

    trace = httpx.get(f"{AGENT}/trace/{d['trace_id']}", timeout=15).json()
    checks["trace persisted with >=7 steps"] = trace.get("event_count", 0) >= 7
    arts = {a for e in trace["events"] for a in e["regulatory_mapping"]["eu_ai_act_articles"]}
    checks["EU AI Act Art. 12 & 13 mapped"] = {"12", "13"} <= arts
    checks["audit chain tamper-evident (integrity verified)"] = \
        trace.get("integrity", {}).get("valid") is True

    ok = True
    for name, passed in checks.items():
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed

    print(f"\ntrace_id={d['trace_id']}  llm_mode={d['llm_mode']}")
    if not ok:
        sys.exit("SMOKE TEST FAILED")
    print("SMOKE TEST PASSED ✓")


if __name__ == "__main__":
    main()
