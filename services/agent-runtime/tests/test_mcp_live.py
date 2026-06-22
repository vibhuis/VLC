"""Live test of the MCP gateway and the agent consuming context over MCP. [paper §4.2]

Skips unless the vcl-gateway MCP server is reachable on :9000.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket

import pytest

MCP_URL = os.environ.get("VCL_MCP_URL", "http://localhost:9000/mcp")


def _reachable() -> bool:
    host, port = "localhost", 9000
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _reachable(), reason="MCP gateway not running on :9000")

PRINCIPAL = {"user": "demo-analyst", "purpose": "supplier_risk_review",
             "org_access": ["EMEA", "AMER", "APAC"]}
WORKED_QUERY = (
    "Show me the top five suppliers in EMEA with contracts expiring before December 2026, "
    "where the contracts contain PII clauses. Only include suppliers whose data subjects "
    "have valid GDPR consent.")


async def _roundtrip():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(MCP_URL) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name for t in (await s.list_tools()).tools}
            res = await s.call_tool("context_graph_query",
                                    {"intent": {"geo": "EMEA", "contains_pii": True,
                                                "end_before": "2026-12-31"}})
            rows = json.loads(res.content[0].text)
            deny = await s.call_tool("policy_check",
                                     {"action": "q", "principal": {"org_access": ["EMEA"]},
                                      "resource": {"geo": "EMEA"}})
            return tools, rows, json.loads(deny.content[0].text)


def test_mcp_exposes_vcl_tools():
    tools, rows, decision = asyncio.run(_roundtrip())
    assert {"semantic_query", "context_graph_query", "policy_check",
            "policy_filter", "feedback_emit"} <= tools
    assert len(rows) == 8                 # worked-case anchors via MCP
    assert decision["outcome"] == "allow"


def test_worked_case_over_mcp():
    from app.graph import run_query
    from app.tools.mcp import MCPToolbox
    out = run_query(WORKED_QUERY, MCPToolbox(), PRINCIPAL)
    f = out["filtered"]
    assert {r["supplier_id"] for r in f["allowed"]} == {f"SUP-00{i}" for i in range(1, 6)}
    assert {r["supplier_id"] for r in f["masked"]} == {"SUP-006", "SUP-007"}
    assert {r["supplier_id"] for r in f["excluded"]} == {"SUP-008"}
