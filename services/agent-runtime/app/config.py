"""Runtime configuration, read from the environment. [spec §3]"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    llm_model: str = os.environ.get("VCL_LLM_MODEL", "gpt-4o")
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    semantic_url: str = os.environ.get("VCL_SEMANTIC_URL", "http://localhost:4000")
    graph_bolt_uri: str = os.environ.get("VCL_GRAPH_BOLT_URI", "bolt://localhost:7687")
    graph_user: str = os.environ.get("VCL_GRAPH_USER", "neo4j")
    graph_password: str = os.environ.get("VCL_GRAPH_PASSWORD", "vcldemopassword")
    policy_url: str = os.environ.get("VCL_POLICY_URL", "http://localhost:8181")
    feedback_url: str = os.environ.get("VCL_FEEDBACK_URL", "http://localhost:8200")
    mcp_url: str = os.environ.get("VCL_MCP_URL", "http://localhost:9000/mcp")
    use_mcp: bool = os.environ.get("VCL_USE_MCP", "0") == "1"
    demo_user: str = os.environ.get("VCL_DEMO_USER", "demo-analyst")
    demo_purpose: str = os.environ.get("VCL_DEMO_PURPOSE", "supplier_risk_review")
    # The scenario clock (consent expiry is judged against this). Matches the data.
    as_of: str = os.environ.get("VCL_AS_OF", "2026-06-18")

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


settings = Settings()
