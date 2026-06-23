"""Build-spec §6 scenario: EMEA suppliers with PII contracts and valid GDPR consent.

Not surfaced in the demo UI (the paper's §5 is the headline), but kept as a governance
scenario that exercises the residency / consent / secrets policies. [DECISIONS D12]
"""
from __future__ import annotations

import calendar
import json
import re

from ..config import settings
from ..llm import PII_MARKER, SECRET_MARKER, _complete, _money, llm_ready
from .base import Scenario

GEO_ALIASES = {
    "emea": "EMEA", "europe": "EMEA", "eu": "EMEA",
    "amer": "AMER", "americas": "AMER", "us": "AMER", "north america": "AMER",
    "apac": "APAC", "asia": "APAC",
}
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _last_day(year: int, month: int) -> int:
    return 31 if month == 12 else calendar.monthrange(year, month)[1]


class SupplierPiiScenario(Scenario):
    name = "supplier_pii"
    label = "Build-spec §6 — PII contracts & GDPR consent"
    description = ("Suppliers in a region with PII contracts expiring before a date, only where "
                  "data subjects have valid GDPR consent and data is hosted in-region.")
    sample_query = (
        "Show me the top five suppliers in EMEA with contracts expiring before December 2026, "
        "where the contracts contain PII clauses. Only include suppliers whose data subjects "
        "have valid GDPR consent.")

    def detect(self, q_lower: str) -> bool:
        if any(re.search(rf"\b{re.escape(a)}\b", q_lower) for a in GEO_ALIASES):
            return True
        return bool(re.search(r"supplier|contract|vendor|consent|clause|gdpr|\bpii\b", q_lower))

    def parse(self, query: str, intent: dict) -> None:
        q = query.lower()
        for alias, geo in GEO_ALIASES.items():
            if re.search(rf"\b{re.escape(alias)}\b", q):
                intent["geo"] = geo
                break
        m = re.search(r"(?:before|by|expir\w*\s+before)\s+([a-z]+)?\s*(\d{4})", q)
        if m:
            year = int(m.group(2))
            month = (m.group(1) or "").strip()
            intent["end_before"] = f"{year}-12-31" if not month or month not in _MONTHS \
                else f"{year}-{_MONTHS[month]:02d}-{_last_day(year, _MONTHS[month])}"
        if re.search(r"\bpii\b|personal data|personally identifiable", q):
            intent["contains_pii"] = True
        if re.search(r"secret|confidential", q):
            intent["contains_secrets"] = True
        if re.search(r"valid.*consent|gdpr consent|consent.*valid", q):
            intent["require_valid_consent"] = True
        if intent.get("geo") == "EMEA" or "gdpr" in q or re.search(r"\beu\b", q):
            intent["residency_scope"] = "EU"
        m = re.search(r"top\s+(\d+|five|ten|three)", q)
        if m:
            word = {"three": 3, "five": 5, "ten": 10}.get(m.group(1))
            intent["limit"] = word if word else int(m.group(1))

    # ----------------------------------------------------------------- policy
    def policy_filter(self, toolbox, rows, principal, intent, as_of) -> dict:
        residency_scope = intent.get("residency_scope", "GLOBAL")
        purpose = principal.get("purpose", "")
        allowed: list[dict] = []
        masked: list[dict] = []
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
            pii = toolbox._decide("allow_pii_field_access", {
                "as_of": as_of, "principal": {"purpose": purpose},
                "resource": {"consent_retention_until": row.get("consent_retention_until")}})
            decisions.append({**pii, "supplier_id": sid})
            secrets = toolbox._decide("mask_secrets_in_response",
                                      {"resource": {"contains_secrets": bool(row.get("contains_secrets"))}})
            decisions.append({**secrets, "supplier_id": sid})

            redactions: list[dict] = []
            if pii.get("outcome") == "mask":
                redactions.append({"field": "pii_fields", "policy": "allow_pii_field_access",
                                   "reasons": pii.get("reasons", [])})
            if secrets.get("outcome") == "mask":
                redactions.append({"field": "secret_clauses", "policy": "mask_secrets_in_response",
                                   "reasons": secrets.get("reasons", [])})
            enriched = {**row, "redactions": redactions}
            (masked if pii.get("outcome") == "mask" else allowed).append(enriched)

        rank = intent.get("rank_by", "value_usd")
        allowed.sort(key=lambda r: r.get(rank, 0), reverse=True)
        masked.sort(key=lambda r: r.get(rank, 0), reverse=True)
        return {"allowed": allowed, "masked": masked, "excluded": excluded, "decisions": decisions}

    # ----------------------------------------------------------------- synthesis
    def _describe(self, intent: dict) -> str:
        parts = []
        if intent.get("geo"):
            parts.append(intent["geo"])
        if intent.get("contains_pii"):
            parts.append("PII contracts")
        if intent.get("contains_secrets"):
            parts.append("secret clauses")
        if intent.get("end_before"):
            parts.append(f"expiring on/before {intent['end_before']}")
        if intent.get("require_valid_consent"):
            parts.append("valid GDPR consent")
        return " · ".join(parts) if parts else "all suppliers"

    def synthesize(self, intent, filtered, limit):
        if llm_ready():
            try:
                return self._llm(intent, filtered, limit), settings.llm_model
            except Exception:
                pass
        return self._deterministic(intent, filtered, limit), "deterministic"

    def _deterministic(self, intent, filtered, limit) -> str:
        allowed, masked, excluded = filtered["allowed"], filtered["masked"], filtered["excluded"]
        shown = allowed[:limit] if limit else allowed
        lines = [f"Top {len(shown)} suppliers — {self._describe(intent)}:", ""]
        for i, r in enumerate(shown, 1):
            secret_note = f" {SECRET_MARKER}" if any(
                x["policy"] == "mask_secrets_in_response" for x in r.get("redactions", [])) else ""
            lines.append(f"{i}. {r['name']} ({r['region']}) — contract {r['contract_id']} "
                         f"expires {r['end_date']}, value {_money(r['value_usd'])} "
                         f"[risk: {r['risk_tier']}]{secret_note}")
        if masked:
            lines += ["", "Withheld — matched the query but failed a policy check:"]
            for r in masked:
                lines.append(f"  • {r['name']} ({r['region']}) — {PII_MARKER} "
                             "(GDPR consent expired or missing)")
        if excluded:
            lines += ["", "Excluded — outside the permitted data-residency scope:"]
            for r in excluded:
                lines.append(f"  • {r['name']} ({r['region']}) — excluded by policy "
                             "require_residency_match (data hosted outside the EU)")
        return "\n".join(lines)

    def _llm(self, intent, filtered, limit) -> str:
        payload = {"allowed": filtered["allowed"][:limit] if limit else filtered["allowed"],
                   "masked": filtered["masked"], "excluded": filtered["excluded"]}
        system = (
            "You are the response-synthesis node of a governed enterprise AI system. Write a "
            "concise analyst answer using ONLY the supplied data. Do not invent suppliers or "
            "values. List allowed suppliers as a ranked top-N. For each masked supplier show the "
            f"marker '{PII_MARKER}' and the reason. For each excluded supplier state it was "
            "excluded by policy require_residency_match. If an allowed supplier's redactions "
            f"include mask_secrets_in_response, append '{SECRET_MARKER}'. Keep it regulator-readable.")
        return _complete(system, f"Question: {intent['raw']}\n\nGoverned data (JSON):\n"
                                 f"{json.dumps(payload, indent=2)}", max_tokens=1200)
