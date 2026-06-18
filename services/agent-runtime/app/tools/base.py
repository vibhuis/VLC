"""Agent tool surface — one tool per VCL component. [spec §5.4]

``Toolbox`` defines the six tools the LangGraph pipeline calls. The per-policy decision
(``_decide``) and the data-access tools (``semantic_query`` / ``graph_query`` /
``feedback_emit``) are abstract — implemented against live services in ``live.py`` and
against deterministic fixtures in ``fixtures.py``. The orchestration that turns
individual policy decisions into row-level allow/mask/exclude outcomes
(``policy_check`` / ``policy_filter``) lives here, so both paths enforce policy identically.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

GEO_ALIASES = {
    "emea": "EMEA", "europe": "EMEA", "eu": "EMEA",
    "amer": "AMER", "americas": "AMER", "us": "AMER", "north america": "AMER",
    "apac": "APAC", "asia": "APAC",
}
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def parse_intent(query: str) -> dict:
    """semantic_layer.parse — map a business-language question to a governed query.

    Rule-based mapping over the semantic layer's known dimensions (region/geo, contract
    end date, PII flag, consent). Deterministic, so the same question always produces the
    same structured intent. [spec §5.4: semantic_layer.parse]
    """
    q = query.lower()
    intent: dict[str, Any] = {"raw": query, "limit": None, "rank_by": "value_usd"}

    for alias, geo in GEO_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", q):
            intent["geo"] = geo
            break

    # "expiring before December 2026" / "before 2026" → an upper bound on end_date.
    m = re.search(r"(?:before|by|expir\w*\s+before)\s+([a-z]+)?\s*(\d{4})", q)
    if m:
        year = int(m.group(2))
        month_name = (m.group(1) or "").strip()
        # Interpret "before <Month> <Year>" inclusively to end-of-that-period, matching
        # the worked-use-case filter (paper §5: contracts expiring before December 2026).
        intent["end_before"] = f"{year}-12-31" if not month_name or month_name not in _MONTHS \
            else f"{year}-{_MONTHS[month_name]:02d}-{_last_day(year, _MONTHS[month_name])}"

    if re.search(r"\bpii\b|personal data|personally identifiable", q):
        intent["contains_pii"] = True

    if re.search(r"valid.*consent|gdpr consent|consent.*valid", q):
        intent["require_valid_consent"] = True

    # EU/EMEA/GDPR framing means the question concerns EU data subjects → residency scope.
    if intent.get("geo") == "EMEA" or "gdpr" in q or re.search(r"\beu\b", q):
        intent["residency_scope"] = "EU"

    m = re.search(r"top\s+(\d+|five|ten|three)", q)
    if m:
        word = {"three": 3, "five": 5, "ten": 10}.get(m.group(1))
        intent["limit"] = word if word else int(m.group(1))

    return intent


def _last_day(year: int, month: int) -> int:
    if month == 12:
        return 31
    import calendar
    return calendar.monthrange(year, month)[1]


class Toolbox(ABC):
    """The six VCL tools the agent runtime calls. [spec §5.4]"""

    # ---- abstract: per-deployment implementations ----
    @abstractmethod
    def _decide(self, rule: str, payload: dict) -> dict:
        """policy_engine.<rule> — return {policy, allow, outcome, reasons, ...}."""

    @abstractmethod
    def semantic_query(self, intent: dict) -> dict:
        """semantic_layer.query — governed measure/dimension query (Cube)."""

    @abstractmethod
    def graph_query(self, intent: dict) -> list[dict]:
        """context_graph.query — matching supplier-contract rows with provenance."""

    @abstractmethod
    def feedback_emit(self, event: dict) -> None:
        """feedback_loop.emit — persist one trace event."""

    # ---- concrete: shared policy orchestration ----
    def parse(self, query: str) -> dict:
        return parse_intent(query)

    def policy_check(self, action: str, principal: dict, resource: dict) -> dict:
        """policy_engine.check — gate the whole request before any data access."""
        d = self._decide("allow_supplier_query",
                         {"principal": principal, "resource": resource, "action": action})
        d.setdefault("policy", "allow_supplier_query")
        return d

    def policy_filter(self, rows: list[dict], principal: dict, intent: dict, as_of: str) -> dict:
        """policy_engine.filter — per-row allow / mask / exclude with redactions.

        Applies require_residency_match (exclude), allow_pii_field_access (mask on expired
        consent) and mask_secrets_in_response (mask secret clauses) to every row. [spec §6]
        """
        residency_scope = intent.get("residency_scope", "GLOBAL")
        purpose = principal.get("purpose", "")
        allowed: list[dict] = []
        masked: list[dict] = []
        excluded: list[dict] = []
        decisions: list[dict] = []

        for row in rows:
            residency = self._decide("require_residency_match", {
                "context": {"residency_scope": residency_scope},
                "resource": {"data_residency": row.get("data_residency")},
            })
            decisions.append({**residency, "supplier_id": row.get("supplier_id")})

            if residency.get("outcome") == "deny":
                # Excluded → record an audit obligation (audit_required_on_decline).
                audit = self._decide("audit_required_on_decline", {"decision": {"outcome": "deny"}})
                decisions.append({**audit, "supplier_id": row.get("supplier_id")})
                excluded.append({**row, "excluded_by": "require_residency_match",
                                 "reasons": residency.get("reasons", [])})
                continue

            pii = self._decide("allow_pii_field_access", {
                "as_of": as_of,
                "principal": {"purpose": purpose},
                "resource": {"consent_retention_until": row.get("consent_retention_until")},
            })
            decisions.append({**pii, "supplier_id": row.get("supplier_id")})

            secrets = self._decide("mask_secrets_in_response",
                                   {"resource": {"contains_secrets": bool(row.get("contains_secrets"))}})
            decisions.append({**secrets, "supplier_id": row.get("supplier_id")})

            redactions: list[dict] = []
            if pii.get("outcome") == "mask":
                redactions.append({"field": "pii_fields", "policy": "allow_pii_field_access",
                                   "reasons": pii.get("reasons", [])})
            if secrets.get("outcome") == "mask":
                redactions.append({"field": "secret_clauses", "policy": "mask_secrets_in_response",
                                   "reasons": secrets.get("reasons", [])})

            enriched = {**row, "redactions": redactions}
            if pii.get("outcome") == "mask":
                masked.append(enriched)
            else:
                allowed.append(enriched)

        rank = intent.get("rank_by", "value_usd")
        allowed.sort(key=lambda r: r.get(rank, 0), reverse=True)
        masked.sort(key=lambda r: r.get(rank, 0), reverse=True)
        return {"allowed": allowed, "masked": masked, "excluded": excluded, "decisions": decisions}
