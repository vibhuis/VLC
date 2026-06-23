"""Fixture toolbox — deterministic, no running services. [DECISIONS D1]

Backs the hermetic test suite: graph rows come from ``data/synthetic/fixtures.json``
(the same records the live stack is seeded with), and ``_decide`` is a faithful Python
mirror of ``vcl.rego``. ``tests/test_policy_parity.py`` asserts this mirror agrees with
the live OPA service, so the two never drift.
"""
from __future__ import annotations

import json
from pathlib import Path

from .base import Toolbox

ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "data" / "synthetic" / "fixtures.json"
KNOWN_PURPOSES = {"supplier_risk_review", "supplier_pii_processing"}


def _load() -> dict:
    return json.loads(FIXTURES.read_text())


class FixtureToolbox(Toolbox):
    def __init__(self, data: dict | None = None):
        self.data = data or _load()
        self._by_supplier = {s["id"]: s for s in self.data["suppliers"]}
        self._consent = {c["supplier_id"]: c for c in self.data["consents"]}
        self.emitted: list[dict] = []

    # ---- policy mirror of vcl.rego ----
    def _decide(self, rule: str, payload: dict) -> dict:
        if rule == "allow_supplier_query":
            org = (payload.get("principal") or {}).get("org_access", [])
            geo = (payload.get("resource") or {}).get("geo")
            allow = "*" in org or geo in org
            return {"policy": rule, "allow": allow, "outcome": "allow" if allow else "deny",
                    "reasons": ["organisational access granted for the supplier's region"] if allow
                    else ["principal has no organisational access to this region"]}

        if rule == "allow_pii_field_access":
            as_of = payload.get("as_of", "")
            purpose = (payload.get("principal") or {}).get("purpose", "")
            retention = (payload.get("resource") or {}).get("consent_retention_until")
            has_purpose = purpose != "" and purpose in KNOWN_PURPOSES
            consent_valid = bool(retention) and retention >= as_of
            if not has_purpose:
                return {"policy": rule, "allow": False, "outcome": "deny",
                        "reasons": ["no valid purpose binding for PII access"]}
            if consent_valid:
                return {"policy": rule, "allow": True, "outcome": "allow",
                        "reasons": ["purpose binding present and data-subject consent valid"]}
            return {"policy": rule, "allow": False, "outcome": "mask",
                    "reasons": ["purpose binding present but data-subject consent expired or missing — PII fields masked"]}

        if rule == "require_residency_match":
            scope = (payload.get("context") or {}).get("residency_scope")
            res = (payload.get("resource") or {}).get("data_residency")
            if scope != "EU":
                return {"policy": rule, "allow": True, "outcome": "allow",
                        "reasons": ["no residency constraint applies to this query"]}
            ok = res == "EU"
            return {"policy": rule, "allow": ok, "outcome": "allow" if ok else "deny",
                    "reasons": ["data residency matches the required EU scope"] if ok
                    else ["EU-subject query but data is hosted outside the EU — row excluded"]}

        if rule == "mask_secrets_in_response":
            secrets = (payload.get("resource") or {}).get("contains_secrets") is True
            return {"policy": rule, "allow": not secrets, "outcome": "mask" if secrets else "allow",
                    "reasons": ["secret clauses must be summarised, not quoted — content masked"] if secrets
                    else ["no secret clauses present"]}

        if rule == "redact_commercial_terms":
            confidential = (payload.get("resource") or {}).get("commercial_confidential") is True
            cleared = "contract_detail" in (payload.get("principal") or {}).get("clearance", [])
            redact = confidential and not cleared
            return {"policy": rule, "allow": not redact, "outcome": "mask" if redact else "allow",
                    "reasons": ["specific commercial term redacted; aggregate exposure disclosable"] if redact
                    else ["principal cleared for contract-level detail, or term not confidential"]}

        if rule == "mask_supplier_contact_pii":
            present = (payload.get("resource") or {}).get("has_contact_pii") is True
            return {"policy": rule, "allow": not present, "outcome": "mask" if present else "allow",
                    "reasons": ["supplier-contact PII (email/phone) masked for this role"] if present
                    else ["no supplier-contact PII present"]}

        if rule == "audit_required_on_decline":
            outcome = (payload.get("decision") or {}).get("outcome", "unknown")
            req = outcome in {"deny", "mask"}
            return {"policy": rule, "audit_required": req, "outcome": outcome,
                    "reasons": ["a decline/mask outcome must emit a structured audit event with reason"] if req
                    else ["no audit obligation for an allow outcome"]}

        raise ValueError(f"unknown rule {rule}")

    # ---- semantic layer ----
    def semantic_query(self, intent: dict) -> dict:
        totals: dict[str, int] = {}
        for s in self.data["suppliers"]:
            for c in self.data["contracts"]:
                if c["supplier_id"] == s["id"]:
                    totals[s["geo"]] = totals.get(s["geo"], 0) + c["value_usd"]
        return {"query": {"measures": ["supplier_risk_view.contracts_total_value_usd"],
                          "dimensions": ["supplier_risk_view.geo"]},
                "data": [{"supplier_risk_view.geo": g, "supplier_risk_view.contracts_total_value_usd": v}
                         for g, v in sorted(totals.items())]}

    # ---- context graph ----
    def graph_query(self, intent: dict) -> list[dict]:
        if intent.get("scenario") == "penalty_delivery":
            return self._graph_query_penalty(intent)
        geo = intent.get("geo")
        want_pii = intent.get("contains_pii")
        want_secrets = intent.get("contains_secrets")
        end_before = intent.get("end_before")
        rows: list[dict] = []
        for c in self.data["contracts"]:
            s = self._by_supplier[c["supplier_id"]]
            if geo is not None and s["geo"] != geo:
                continue
            if want_pii is not None and bool(c["contains_pii"]) != bool(want_pii):
                continue
            if want_secrets is not None and bool(c["contains_secrets"]) != bool(want_secrets):
                continue
            if end_before is not None and c["end_date"] > end_before:
                continue
            cn = self._consent.get(s["id"])
            rows.append({
                "supplier_id": s["id"], "name": s["name"], "region": s["region"],
                "geo": s["geo"], "data_residency": s["data_residency"],
                "gdpr_consent_status": s["gdpr_consent_status"], "risk_tier": s["risk_tier"],
                "contract_id": c["id"], "end_date": c["end_date"], "value_usd": c["value_usd"],
                "contains_secrets": bool(c["contains_secrets"]),
                "consent_retention_until": cn["retention_until"] if cn else None,
            })
        rows.sort(key=lambda r: r["value_usd"], reverse=True)
        return rows

    def _graph_query_penalty(self, intent: dict) -> list[dict]:
        quarter = intent.get("quarter")
        minexp = intent.get("penalty_exposure_min", 1_000_000)
        rows: list[dict] = []
        for c in self.data["contracts"]:
            if c["penalty_exposure"] <= minexp:
                continue
            if quarter is not None and c["quarter"] != quarter:
                continue
            s = self._by_supplier[c["supplier_id"]]
            rows.append({
                "supplier_id": s["id"], "name": s["name"], "region": s["region"], "geo": s["geo"],
                "data_residency": s["data_residency"],
                "risk_tier": s["risk_tier"], "delivery_risk_score": s["delivery_risk_score"],
                "delivery_at_risk": bool(s["delivery_at_risk"]),
                "contact_name": s["contact_name"], "contact_email": s["contact_email"],
                "contact_phone": s["contact_phone"], "contract_id": c["id"], "quarter": c["quarter"],
                "penalty_amount": c["penalty_amount"], "penalty_probability": c["penalty_probability"],
                "penalty_exposure": c["penalty_exposure"],
                "commercial_confidential": bool(c["commercial_confidential"]),
                "system_refs": [f"ERP:{s['erp_id']}", f"MES:{s['mes_id']}", f"CMS:{s['cms_id']}"],
            })
        rows.sort(key=lambda r: r["penalty_exposure"], reverse=True)
        return rows

    # ---- feedback loop ----
    def feedback_emit(self, event: dict) -> None:
        self.emitted.append(event)
