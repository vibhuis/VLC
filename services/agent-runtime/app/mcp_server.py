"""MCP gateway — exposes the VCL tools over the Model Context Protocol. [paper §4.2, ref 34]

The paper specifies the agent/tool runtime as "the surface through which agentic workloads
consume context and invoke enterprise actions… it implements MCP." This server is that
surface: it publishes the governed VCL tools (semantic query, context-graph query, policy
check/filter, audit emit) as MCP tools. Any MCP client — this repo's agent, MCP Inspector,
or an external copilot — consumes enterprise context through it, and every access is still
policy-enforced and audit-chained by the components behind it.

Run:  python -m app.mcp_server   (serves Streamable HTTP at :9000/mcp)
"""
from __future__ import annotations

import json
import os

from mcp.server.fastmcp import FastMCP

from .tools.live import LiveToolbox

mcp = FastMCP("vcl-gateway", host="0.0.0.0", port=int(os.environ.get("VCL_MCP_PORT", "9000")))

_toolbox: LiveToolbox | None = None


def _tb() -> LiveToolbox:
    global _toolbox
    if _toolbox is None:
        _toolbox = LiveToolbox()
    return _toolbox


# Tools return JSON strings so results are transport-agnostic across MCP clients.
@mcp.tool()
def semantic_query(intent: dict) -> str:
    """Governed aggregate over the semantic layer (Cube) for the given structured intent."""
    return json.dumps(_tb().semantic_query(intent))


@mcp.tool()
def context_graph_query(intent: dict) -> str:
    """Retrieve matching supplier-contract rows with provenance from the context graph (Neo4j)."""
    return json.dumps(_tb().graph_query(intent))


@mcp.tool()
def policy_check(action: str, principal: dict, resource: dict) -> str:
    """Gate an action via the policy engine (OPA) — returns {policy, allow, outcome, reasons}."""
    return json.dumps(_tb().policy_check(action, principal, resource))


@mcp.tool()
def policy_filter(rows: list, principal: dict, intent: dict, as_of: str) -> str:
    """Per-row allow/mask/exclude with redactions, enforced by the policy engine (OPA)."""
    return json.dumps(_tb().policy_filter(rows, principal, intent, as_of))


@mcp.tool()
def feedback_emit(event: dict) -> str:
    """Persist one trace event into the tamper-evident audit log (feedback loop)."""
    _tb().feedback_emit(event)
    return json.dumps({"ok": True})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
