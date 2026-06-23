"""Agent tool surface — one tool per VCL component. [spec §5.4]

The data-access tools (``_decide`` / ``semantic_query`` / ``graph_query`` /
``feedback_emit``) are abstract — ``live.py`` talks to the real services and ``fixtures.py``
uses deterministic data. Intent parsing and per-row policy orchestration are delegated to
the active **Scenario** plugin (``app/scenarios/``), so the engine stays domain-agnostic:
adding a domain means registering a Scenario and adding its retrieval query, not editing
this file. See docs/adapting-to-your-domain.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .. import scenarios


def parse_intent(query: str) -> dict:
    """semantic_layer.parse — pick the scenario that handles the query and let it parse."""
    intent: dict = {"raw": query, "rank_by": "value_usd", "limit": None}
    scen = scenarios.select(query)
    if scen is None:
        intent["scenario"] = None
        intent["in_domain"] = False
        return intent
    intent["scenario"] = scen.name
    scen.parse(query, intent)
    intent["in_domain"] = True
    return intent


class Toolbox(ABC):
    """The VCL tools the agent runtime calls. [spec §5.4]"""

    # ---- abstract: per-deployment implementations ----
    @abstractmethod
    def _decide(self, rule: str, payload: dict) -> dict:
        """policy_engine.<rule> — return {policy, allow, outcome, reasons, ...}."""

    @abstractmethod
    def semantic_query(self, intent: dict) -> dict:
        """semantic_layer.query — governed measure/dimension query (Cube)."""

    @abstractmethod
    def graph_query(self, intent: dict) -> list[dict]:
        """context_graph.query — rows with provenance (dispatched by intent['scenario'])."""

    @abstractmethod
    def feedback_emit(self, event: dict) -> None:
        """feedback_loop.emit — persist one trace event."""

    # ---- concrete: scenario-driven orchestration ----
    def parse(self, query: str) -> dict:
        return parse_intent(query)

    def policy_check(self, action: str, principal: dict, resource: dict) -> dict:
        """policy_engine.check — gate the whole request before any data access."""
        d = self._decide("allow_supplier_query",
                         {"principal": principal, "resource": resource, "action": action})
        d.setdefault("policy", "allow_supplier_query")
        return d

    def policy_filter(self, rows: list[dict], principal: dict, intent: dict, as_of: str) -> dict:
        """policy_engine.filter — delegate to the active scenario's policy orchestration."""
        scen = scenarios.get(intent.get("scenario"))
        if scen is None:
            return {"allowed": [], "masked": [], "excluded": [], "decisions": []}
        return scen.policy_filter(self, rows, principal, intent, as_of)
