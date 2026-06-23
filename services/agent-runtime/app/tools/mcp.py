"""MCP toolbox — the agent consumes VCL context over the Model Context Protocol. [paper §4.2]

When VCL_USE_MCP=1, the agent runs its semantic/graph/policy/feedback tools as MCP calls to
the vcl-gateway server instead of in-process clients — making "the agent runtime implements
MCP" literally true. Parsing (understanding) stays local; everything that touches enterprise
context goes through MCP, where it is still governed and audit-chained.
"""
from __future__ import annotations

import asyncio
import json

from ..config import settings
from ..llm import llm_parse_fields, llm_ready
from .base import Toolbox, parse_intent


class MCPToolbox(Toolbox):
    def __init__(self) -> None:
        base = settings.mcp_url.rstrip("/")
        self.url = base if base.endswith("/mcp") else base + "/mcp"

    def _call(self, name: str, args: dict):
        async def go():
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
            async with streamablehttp_client(self.url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(name, args)
                    text = next((c.text for c in result.content if getattr(c, "type", "") == "text"), "null")
                    return json.loads(text)
        return asyncio.run(go())

    # understanding stays local; data access goes over MCP
    def parse(self, query: str) -> dict:
        intent = parse_intent(query)
        if intent.get("in_domain") and llm_ready():
            fields = llm_parse_fields(query)
            if fields:
                intent.update(fields)
        return intent

    # everything that consumes enterprise context goes over MCP
    def semantic_query(self, intent: dict) -> dict:
        return self._call("semantic_query", {"intent": intent})

    def graph_query(self, intent: dict) -> list[dict]:
        return self._call("context_graph_query", {"intent": intent})

    def policy_check(self, action: str, principal: dict, resource: dict) -> dict:
        return self._call("policy_check", {"action": action, "principal": principal, "resource": resource})

    def policy_filter(self, rows: list[dict], principal: dict, intent: dict, as_of: str) -> dict:
        return self._call("policy_filter",
                          {"rows": rows, "principal": principal, "intent": intent, "as_of": as_of})

    def feedback_emit(self, event: dict) -> None:
        self._call("feedback_emit", {"event": event})

    # required by the ABC; unused because the coarse policy tools are overridden above
    def _decide(self, rule: str, payload: dict) -> dict:  # pragma: no cover
        raise NotImplementedError("MCPToolbox routes policy via the policy_check/policy_filter MCP tools")
