"""Paper §5 scenario: penalty-clause exposure + at-risk delivery from telemetry."""
from __future__ import annotations

import json
import re

from ..config import settings
from ..llm import (CONTACT_MARKER, COMMERCIAL_MARKER, _complete, _money, llm_ready)
from .base import Scenario


class PenaltyDeliveryScenario(Scenario):
    name = "penalty_delivery"
    label = "Paper §5 — penalty exposure & at-risk delivery"
    description = ("Q3 contracts with penalty-clause exposure over a threshold, and which of "
                  "those suppliers have at-risk delivery from 6 months of operational telemetry.")
    sample_query = (
        "Which Q3 supplier contracts have penalty-clause exposure greater than one million "
        "dollars, and which of those suppliers have at-risk delivery performance based on the "
        "last six months of operational telemetry?")

    def detect(self, q_lower: str) -> bool:
        return bool(re.search(r"penalt|exposure|delivery|telemetry|at[ -]risk", q_lower))

    def parse(self, query: str, intent: dict) -> None:
        q = query.lower()
        intent["rank_by"] = "penalty_exposure"
        mq = re.search(r"\bq([1-4])\b|quarter\s*([1-4])", q)
        if mq:
            intent["quarter"] = f"FY26-Q{mq.group(1) or mq.group(2)}"
        me = re.search(r"\$?\s*(\d+(?:\.\d+)?)\s*(million|m|billion|bn)\b", q)
        if me:
            mult = 1_000_000 if me.group(2) in ("million", "m") else 1_000_000_000
            intent["penalty_exposure_min"] = int(float(me.group(1)) * mult)
        elif "million" in q or "exposure" in q:
            intent["penalty_exposure_min"] = 1_000_000  # "one million dollars"
        if re.search(r"at[ -]risk|delivery", q):
            intent["delivery_at_risk"] = True
        # cross-border procurement query → EU data-residency governs (paper §4.3)
        intent["residency_scope"] = "EU"

    # ----------------------------------------------------------------- policy
    def policy_filter(self, toolbox, rows, principal, intent, as_of) -> dict:
        want_at_risk = intent.get("delivery_at_risk", True)
        residency_scope = intent.get("residency_scope", "EU")
        allowed: list[dict] = []
        excluded: list[dict] = []
        decisions: list[dict] = []
        for row in rows:
            sid = row.get("supplier_id")
            residency = toolbox._decide("require_residency_match", {
                "context": {"residency_scope": residency_scope},
                "resource": {"data_residency": row.get("data_residency")}})
            decisions.append({**residency, "supplier_id": sid})
            if residency.get("outcome") == "deny":
                decisions.append({**toolbox._decide("audit_required_on_decline",
                                                    {"decision": {"outcome": "deny"}}), "supplier_id": sid})
                excluded.append({**row, "excluded_by": "require_residency_match",
                                 "reasons": residency.get("reasons", [])})
                continue
            if want_at_risk and not row.get("delivery_at_risk"):
                excluded.append({**row, "excluded_by": "delivery_within_tolerance",
                                 "reasons": ["penalty exposure flagged but delivery "
                                             "performance within tolerance"]})
                continue
            commercial = toolbox._decide("redact_commercial_terms", {
                "principal": {"clearance": principal.get("clearance", [])},
                "resource": {"commercial_confidential": bool(row.get("commercial_confidential"))}})
            decisions.append({**commercial, "supplier_id": sid})
            contact = toolbox._decide("mask_supplier_contact_pii",
                                      {"resource": {"has_contact_pii": bool(row.get("contact_email"))}})
            decisions.append({**contact, "supplier_id": sid})

            redactions: list[dict] = []
            if commercial.get("outcome") == "mask":
                decisions.append({**toolbox._decide("audit_required_on_decline",
                                                    {"decision": {"outcome": "mask"}}), "supplier_id": sid})
                redactions.append({"field": "penalty_amount", "policy": "redact_commercial_terms",
                                   "reasons": commercial.get("reasons", [])})
            if contact.get("outcome") == "mask":
                redactions.append({"field": "supplier_contact", "policy": "mask_supplier_contact_pii",
                                   "reasons": contact.get("reasons", [])})
            allowed.append({**row, "redactions": redactions})

        allowed.sort(key=lambda r: r.get("penalty_exposure", 0), reverse=True)
        return {"allowed": allowed, "masked": [], "excluded": excluded, "decisions": decisions}

    # ----------------------------------------------------------------- synthesis
    def _describe(self, intent: dict) -> str:
        parts = []
        if intent.get("quarter"):
            parts.append(intent["quarter"])
        parts.append(f"penalty exposure > {_money(intent.get('penalty_exposure_min', 1_000_000))}")
        if intent.get("delivery_at_risk"):
            parts.append("at-risk delivery")
        return " · ".join(parts)

    def synthesize(self, intent, filtered, limit):
        allowed = filtered["allowed"][:limit] if limit else filtered["allowed"]
        excluded = filtered["excluded"]
        if llm_ready():
            try:
                return self._llm(intent, allowed, excluded), settings.llm_model
            except Exception:
                pass
        return self._deterministic(intent, allowed, excluded), "deterministic"

    def _deterministic(self, intent, allowed, excluded) -> str:
        def has(r, p):
            return any(x["policy"] == p for x in r.get("redactions", []))
        lines = [f"Suppliers matching {self._describe(intent)}, ranked by penalty exposure:", ""]
        for i, r in enumerate(allowed, 1):
            term = COMMERCIAL_MARKER if has(r, "redact_commercial_terms") else _money(r["penalty_amount"])
            contact = CONTACT_MARKER if has(r, "mask_supplier_contact_pii") else r.get("contact_email", "")
            refs = ", ".join(r.get("system_refs", []))
            lines.append(f"{i}. {r['name']} ({r['region']}) — contract {r['contract_id']} ({r['quarter']}), "
                         f"penalty exposure {_money(r['penalty_exposure'])} (specific penalty term: {term}), "
                         f"delivery-risk {r['delivery_risk_score']:.2f} [at-risk]")
            lines.append(f"     contact: {contact} · resolved across {refs}")
        residency = [r for r in excluded if r.get("excluded_by") == "require_residency_match"]
        delivery = [r for r in excluded if r.get("excluded_by") == "delivery_within_tolerance"]
        if residency:
            lines += ["", "Excluded — operational data hosted outside the EU "
                      "(policy require_residency_match):"]
            for r in residency:
                lines.append(f"  • {r['name']} ({r['region']}) — penalty exposure "
                             f"{_money(r['penalty_exposure'])}, data residency {r.get('data_residency')}")
        if delivery:
            lines += ["", "Flagged — penalty exposure over threshold but delivery within tolerance "
                      "(not at-risk):"]
            for r in delivery:
                lines.append(f"  • {r['name']} ({r['region']}) — penalty exposure "
                             f"{_money(r['penalty_exposure'])}, delivery-risk {r['delivery_risk_score']:.2f}")
        return "\n".join(lines)

    def _llm(self, intent, allowed, excluded) -> str:
        payload = {"allowed": allowed, "excluded": excluded}
        system = (
            "You are the response-synthesis node of a governed enterprise AI system. Write a "
            "concise analyst answer using ONLY the supplied data; do not invent values. List the "
            "allowed suppliers ranked by penalty exposure; show the aggregate penalty exposure. "
            f"Where a supplier's redactions include redact_commercial_terms, show '{COMMERCIAL_MARKER}' "
            f"instead of the specific penalty amount. Where they include mask_supplier_contact_pii, "
            f"show '{CONTACT_MARKER}' instead of the contact. Note 'excluded' suppliers were either "
            "outside the EU (require_residency_match) or had delivery within tolerance. "
            "Keep it regulator-readable.")
        return _complete(system, f"Question: {intent['raw']}\n\nGoverned data (JSON):\n"
                                 f"{json.dumps(payload, indent=2)}", max_tokens=1200)
