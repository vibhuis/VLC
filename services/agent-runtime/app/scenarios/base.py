"""Scenario plugins — the single extension surface for adapting the VCL to a new domain.

A `Scenario` owns the domain-specific behaviour for one family of questions:
  • detect()       — does this scenario handle the query?
  • parse()        — extract the structured intent fields it needs
  • policy_filter() — turn graph rows into allow/mask/exclude with redactions (via OPA)
  • synthesize()   — write the analyst answer (LLM, with a deterministic fallback)

Everything else (the LangGraph pipeline, the tamper-evident audit log, the MCP gateway,
the feedback loop) is domain-agnostic and drives scenarios through this interface and the
registry below. To add a domain you register a new Scenario and add its data-retrieval
query to the toolboxes — see docs/adapting-to-your-domain.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Scenario(ABC):
    #: machine name, also the value of intent["scenario"] and the toolbox query key
    name: str
    #: human label (shown in the UI)
    label: str
    #: a sample question that this scenario answers (pre-filled in the UI)
    sample_query: str
    #: one-line description
    description: str = ""

    @abstractmethod
    def detect(self, q_lower: str) -> bool:
        """True if this scenario should handle the (lower-cased) query."""

    @abstractmethod
    def parse(self, query: str, intent: dict) -> None:
        """Fill scenario-specific fields on `intent` (already has raw/rank_by/limit)."""

    @abstractmethod
    def policy_filter(self, toolbox, rows: list[dict], principal: dict,
                      intent: dict, as_of: str) -> dict:
        """Return {allowed, masked, excluded, decisions} using toolbox._decide (OPA)."""

    @abstractmethod
    def synthesize(self, intent: dict, filtered: dict, limit: int | None) -> tuple[str, str]:
        """Return (answer_text, mode) where mode is the model id or 'deterministic'."""


_REGISTRY: list[Scenario] = []


def register(scenario: Scenario) -> None:
    _REGISTRY.append(scenario)


def all_scenarios() -> list[Scenario]:
    return list(_REGISTRY)


def get(name: str) -> Scenario | None:
    return next((s for s in _REGISTRY if s.name == name), None)


def select(query: str) -> Scenario | None:
    """First registered scenario whose detect() matches the query (None → out of domain)."""
    q = query.lower()
    return next((s for s in _REGISTRY if s.detect(q)), None)
