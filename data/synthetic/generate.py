#!/usr/bin/env python3
"""Synthetic supplier-contract data generator. [paper §5; build-spec §5.1/§5.2/§6]

Deterministic (fixed seed). Produces data for BOTH worked use cases:

  • build-spec §6  — EMEA suppliers with PII contracts expiring before 2026-12-31 and
    valid GDPR consent → 5 shown / 2 masked (expired consent) / 1 excluded (US residency).

  • paper §5       — Q3 supplier contracts with penalty-clause exposure > $1M and the
    suppliers among those with at-risk delivery performance (from 6 months of operational
    telemetry). Adds penalty clauses, a DeliveryRiskScore from telemetry, cross-system
    identity resolution (ERP/MES/CMS ids), and supplier contacts. → 5 at-risk shown
    (2 with commercial terms redacted, all with contact PII masked), 2 flagged
    exposure>$1M but delivery within tolerance, 1 below the exposure threshold.

The §5 layer is applied AFTER the §6 build with a separate RNG, so the §6 anchors and
counts are unchanged.

Outputs: suppliers.csv, contracts.csv, contract_clauses.csv, consents.csv, telemetry.csv,
fixtures.json, and services/context-graph/seed/load.cypher.

Run:  python data/synthetic/generate.py
"""
from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

AS_OF = date(2026, 6, 18)
SEED = 20599942

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SEED_CYPHER = ROOT / "services" / "context-graph" / "seed" / "load.cypher"

REGIONS = {
    "EMEA-West": ("EMEA", "EU"), "EMEA-North": ("EMEA", "EU"), "UK": ("EMEA", "EU"),
    "US-East": ("AMER", "US"), "US-West": ("AMER", "US"), "APAC": ("APAC", "APAC"),
}
RISK_TIERS = ["low", "medium", "high", "critical"]

# paper §5 anchors: penalty exposure (amount × probability) and delivery at-risk flag.
PAPER_ANCHORS = {
    "SUP-009": dict(amount=4_000_000, prob=0.40, at_risk=True, confidential=False),   # exp 1.60M
    "SUP-010": dict(amount=3_000_000, prob=0.50, at_risk=True, confidential=False),   # exp 1.50M
    "SUP-011": dict(amount=6_000_000, prob=0.30, at_risk=True, confidential=True),    # exp 1.80M
    "SUP-012": dict(amount=2_500_000, prob=0.60, at_risk=True, confidential=False),   # exp 1.50M
    "SUP-013": dict(amount=5_000_000, prob=0.45, at_risk=True, confidential=True),    # exp 2.25M
    "SUP-014": dict(amount=8_000_000, prob=0.30, at_risk=False, confidential=False),  # exp 2.40M, not at-risk
    "SUP-015": dict(amount=3_000_000, prob=0.50, at_risk=False, confidential=False),  # exp 1.50M, not at-risk
    "SUP-016": dict(amount=1_000_000, prob=0.20, at_risk=True, confidential=False),   # exp 0.20M < $1M
}


def _iso(d: date) -> str:
    return d.isoformat()


def _quarter(d: date) -> str:
    return f"FY{d.year % 100}-Q{(d.month - 1) // 3 + 1}"


def build_dataset() -> dict:
    rng = random.Random(SEED)
    suppliers: list[dict] = []
    contracts: list[dict] = []
    clauses: list[dict] = []
    consents: list[dict] = []
    persons: list[dict] = []
    cid = clid = cnid = pid = 0

    def add_contract(supplier_id, end_date, value, pii, secrets, *,
                     penalty_amount=0, penalty_probability=0.0, confidential=False) -> dict:
        nonlocal cid, clid
        cid += 1
        c = {
            "id": f"CON-{cid:03d}", "supplier_id": supplier_id,
            "start_date": _iso(end_date - timedelta(days=rng.randint(365, 1095))),
            "end_date": _iso(end_date), "value_usd": value,
            "contains_pii": pii, "contains_secrets": secrets,
            "quarter": _quarter(end_date),
            "penalty_amount": penalty_amount, "penalty_probability": penalty_probability,
            "penalty_exposure": int(penalty_amount * penalty_probability),
            "commercial_confidential": confidential,
        }
        contracts.append(c)
        clid += 1
        clauses.append({"id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "standard",
                        "text": "Standard master services agreement terms and conditions apply."})
        if pii:
            clid += 1
            clauses.append({"id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "pii",
                            "text": ("Processor handles personal data of EU data subjects including "
                                     "names, contact details and payroll identifiers.")})
        if secrets:
            clid += 1
            clauses.append({"id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "secret",
                            "text": ("CONFIDENTIAL: encryption key escrow procedure and root "
                                     "credential rotation schedule (restricted).")})
        if penalty_amount:
            clid += 1
            clauses.append({"id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "penalty",
                            "text": (f"Late-delivery penalty of up to ${penalty_amount:,} applies, "
                                     f"triggered with probability {penalty_probability:.0%}.")})
        return c

    def add_consent(supplier_id, status):
        nonlocal cnid
        cnid += 1
        if status == "valid":
            retention = AS_OF + timedelta(days=rng.randint(120, 720))
        elif status == "expired":
            retention = AS_OF - timedelta(days=rng.randint(30, 365))
        else:
            return None
        consents.append({"id": f"CNS-{cnid:03d}", "supplier_id": supplier_id,
                         "granted_at": _iso(retention - timedelta(days=730)),
                         "scope": "supplier_pii_processing", "retention_until": _iso(retention)})

    def add_supplier(sid, name, region, residency, consent_status, risk):
        nonlocal pid
        geo = REGIONS[region][0]
        suppliers.append({
            "id": sid, "name": name, "region": region, "geo": geo,
            "data_residency": residency, "gdpr_consent_status": consent_status, "risk_tier": risk,
            # paper §5 fields — populated in _apply_paper_scenario
            "erp_id": "", "mes_id": "", "cms_id": "",
            "delivery_risk_score": 0.0, "delivery_at_risk": False,
            "contact_name": "", "contact_email": "", "contact_phone": "",
        })
        add_consent(sid, consent_status)
        pid += 1
        persons.append({"id": f"PER-{pid:03d}", "supplier_id": sid, "name": f"Data Subject {pid}"})

    # -------- §6 anchors (unchanged) --------
    for sid, name, region, end, val, risk in [
        ("SUP-001", "Helvetia Pharma AG", "EMEA-West", date(2026, 6, 30), 9_800_000, "high"),
        ("SUP-002", "Nordic DataWorks AB", "EMEA-North", date(2026, 9, 15), 7_400_000, "high"),
        ("SUP-003", "Britannia Logistics Ltd", "UK", date(2026, 3, 1), 6_100_000, "medium"),
        ("SUP-004", "Rhein Components GmbH", "EMEA-West", date(2026, 11, 20), 5_250_000, "medium"),
        ("SUP-005", "Iberia Analytics SL", "EMEA-West", date(2026, 8, 10), 4_900_000, "critical"),
    ]:
        add_supplier(sid, name, region, "EU", "valid", risk)
        add_contract(sid, end, val, pii=True, secrets=False)
    for sid, name, region, end, val, risk in [
        ("SUP-006", "Baltic Cloud OU", "EMEA-North", date(2026, 5, 5), 8_300_000, "high"),
        ("SUP-007", "Gallia Secure SAS", "EMEA-West", date(2026, 7, 7), 6_750_000, "critical"),
    ]:
        add_supplier(sid, name, region, "EU", "expired", risk)
        add_contract(sid, end, val, pii=True, secrets=True)
    add_supplier("SUP-008", "Albion Offshore Data Ltd", "UK", "US", "valid", "high")
    add_contract("SUP-008", date(2026, 4, 4), 7_900_000, pii=True, secrets=False)

    # -------- filler (unchanged RNG path) --------
    first_names = ["Acme", "Orion", "Vertex", "Summit", "Cobalt", "Delta", "Pioneer",
                   "Meridian", "Aurora", "Quantum", "Cedar", "Horizon", "Atlas",
                   "Lumen", "Pacific", "Granite", "Sierra", "Nimbus", "Pinnacle",
                   "Beacon", "Forge", "Harbor"]
    suffixes = ["Systems", "Industries", "Partners", "Solutions", "Networks", "Group"]
    regions = list(REGIONS.keys())
    for i in range(9, 31):
        sid = f"SUP-{i:03d}"
        name = f"{first_names[i - 9]} {rng.choice(suffixes)}"
        region = rng.choice(regions)
        residency = REGIONS[region][1]
        consent_status = rng.choices(["valid", "expired", "missing"], weights=[7, 2, 1])[0]
        risk = rng.choice(RISK_TIERS)
        add_supplier(sid, name, region, residency, consent_status, risk)
        for _ in range(rng.randint(2, 5)):
            end = AS_OF + timedelta(days=rng.randint(30, 1400))
            pii = rng.random() < 0.12
            secrets = rng.random() < 0.18
            value = rng.randint(2, 95) * 100_000
            add_contract(sid, end, value, pii=pii, secrets=secrets)

    policy_decisions = [
        {"id": "PDC-001", "policy": "allow_pii_field_access", "outcome": "mask",
         "contract_id": "CON-006", "reason": "consent expired"},
        {"id": "PDC-002", "policy": "allow_pii_field_access", "outcome": "mask",
         "contract_id": "CON-007", "reason": "consent expired"},
        {"id": "PDC-003", "policy": "require_residency_match", "outcome": "deny",
         "contract_id": "CON-008", "reason": "data hosted outside EU"},
    ]

    data = {
        "as_of": _iso(AS_OF), "suppliers": suppliers, "contracts": contracts,
        "contract_clauses": clauses, "consents": consents, "persons": persons,
        "policy_decisions": policy_decisions, "telemetry": [],
    }
    _apply_paper_scenario(data, add_contract)
    return data


def _apply_paper_scenario(data: dict, add_contract) -> None:
    """Layer the paper §5 attributes on top of the §6 dataset (separate RNG)."""
    rng = random.Random(SEED + 1)
    by_id = {s["id"]: s for s in data["suppliers"]}
    telemetry: list[dict] = []

    for idx, s in enumerate(data["suppliers"], start=1):
        n = int(s["id"].split("-")[1])
        s["erp_id"] = f"E{1000 + n}"
        s["mes_id"] = f"M-{n:03d}"
        s["cms_id"] = f"CMS-2026-{n:04d}"
        first = s["name"].split()[0]
        s["contact_name"] = f"{first} Procurement Desk"
        s["contact_email"] = f"contact{n:03d}@{first.lower()}.example"
        s["contact_phone"] = f"+1-555-{1000 + n:04d}"
        # delivery risk: anchors explicit, others mostly within tolerance
        if s["id"] in PAPER_ANCHORS:
            base = {"SUP-009": 0.72, "SUP-010": 0.68, "SUP-011": 0.80, "SUP-012": 0.66,
                    "SUP-013": 0.85, "SUP-014": 0.35, "SUP-015": 0.40, "SUP-016": 0.70}[s["id"]]
        else:
            base = round(rng.uniform(0.10, 0.55), 2)
        s["delivery_risk_score"] = base
        s["delivery_at_risk"] = base >= 0.60
        # 6 months of operational telemetry feeding the score
        for m in range(6, 0, -1):
            month = (AS_OF.replace(day=1) - timedelta(days=30 * (m - 1))).strftime("%Y-%m")
            telemetry.append({
                "id": f"TLM-{n:03d}-{month}", "supplier_id": s["id"], "month": month,
                "on_time_rate": round(max(0.0, 1 - base + rng.uniform(-0.05, 0.05)), 3),
                "incidents": max(0, round(base * 10 + rng.uniform(-1, 1))),
            })

    # Add one Q3 penalty contract per paper anchor (non-PII so it never enters the §6 query).
    for sid, a in PAPER_ANCHORS.items():
        if sid not in by_id:
            continue
        add_contract(sid, date(2026, 8, 15), rng.randint(20, 90) * 100_000,
                     pii=False, secrets=False, penalty_amount=a["amount"],
                     penalty_probability=a["prob"], confidential=a["confidential"])

    data["telemetry"] = telemetry


# --------------------------------------------------------------------------- writers
def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def write_cypher(path: Path, data: dict) -> None:
    L = ["// VCL context-graph seed — generated by data/synthetic/generate.py",
         "// Do not edit by hand; rerun the generator to regenerate.",
         "CREATE CONSTRAINT supplier_id IF NOT EXISTS FOR (s:Supplier) REQUIRE s.id IS UNIQUE;",
         "CREATE CONSTRAINT contract_id IF NOT EXISTS FOR (c:Contract) REQUIRE c.id IS UNIQUE;",
         ""]

    for region, (geo, _res) in REGIONS.items():
        L.append(f"MERGE (:Region {{name:'{region}', geo:'{geo}'}});")
    L.append("")

    for s in data["suppliers"]:
        L.append(
            "MERGE (s:Supplier {{id:'{id}'}}) SET s.name='{name}', s.region='{region}', "
            "s.geo='{geo}', s.data_residency='{res}', s.gdpr_consent_status='{cs}', "
            "s.risk_tier='{rt}', s.erp_id='{erp}', s.mes_id='{mes}', s.cms_id='{cms}', "
            "s.delivery_risk_score={drs}, s.delivery_at_risk={ar}, s.contact_name='{cn}', "
            "s.contact_email='{ce}', s.contact_phone='{cp}' "
            "WITH s MATCH (r:Region {{name:'{region}'}}) MERGE (s)-[:OPERATES_IN]->(r);".format(
                id=s["id"], name=_q(s["name"]), region=s["region"], geo=s["geo"],
                res=s["data_residency"], cs=s["gdpr_consent_status"], rt=s["risk_tier"],
                erp=s["erp_id"], mes=s["mes_id"], cms=s["cms_id"],
                drs=s["delivery_risk_score"], ar=str(s["delivery_at_risk"]).lower(),
                cn=_q(s["contact_name"]), ce=_q(s["contact_email"]), cp=_q(s["contact_phone"])))
    L.append("")

    # Cross-system identity resolution: one SystemRef per source system → canonical Supplier.
    for s in data["suppliers"]:
        for system, ext in (("ERP", s["erp_id"]), ("MES", s["mes_id"]), ("CMS", s["cms_id"])):
            L.append(
                "MATCH (s:Supplier {{id:'{sid}'}}) "
                "MERGE (x:SystemRef {{system:'{sys}', ext_id:'{ext}'}}) "
                "MERGE (x)-[:RESOLVES_TO]->(s);".format(sid=s["id"], sys=system, ext=ext))
    L.append("")

    for p in data["persons"]:
        L.append("MATCH (s:Supplier {{id:'{sid}'}}) MERGE (p:Person {{id:'{id}'}}) "
                 "SET p.name='{name}' MERGE (s)-[:HAS_DATA_SUBJECT]->(p);".format(
                     sid=p["supplier_id"], id=p["id"], name=_q(p["name"])))
    L.append("")

    for c in data["consents"]:
        L.append("MATCH (s:Supplier {{id:'{sid}'}}) MERGE (cn:Consent {{id:'{id}'}}) "
                 "SET cn.granted_at=date('{g}'), cn.scope='{scope}', "
                 "cn.retention_until=date('{r}') MERGE (s)-[:HAS_CONSENT]->(cn);".format(
                     sid=c["supplier_id"], id=c["id"], g=c["granted_at"], scope=c["scope"],
                     r=c["retention_until"]))
    L.append("")

    for c in data["contracts"]:
        L.append(
            "MATCH (s:Supplier {{id:'{sid}'}}) MERGE (c:Contract {{id:'{id}'}}) "
            "SET c.start_date=date('{sd}'), c.end_date=date('{ed}'), c.value_usd={val}, "
            "c.contains_pii={pii}, c.contains_secrets={sec}, c.quarter='{q}', "
            "c.penalty_amount={pa}, c.penalty_probability={pp}, c.penalty_exposure={pe}, "
            "c.commercial_confidential={cc} MERGE (c)-[:BELONGS_TO]->(s);".format(
                sid=c["supplier_id"], id=c["id"], sd=c["start_date"], ed=c["end_date"],
                val=c["value_usd"], pii=str(c["contains_pii"]).lower(),
                sec=str(c["contains_secrets"]).lower(), q=c["quarter"], pa=c["penalty_amount"],
                pp=c["penalty_probability"], pe=c["penalty_exposure"],
                cc=str(c["commercial_confidential"]).lower()))
    L.append("")

    for cl in data["contract_clauses"]:
        L.append("MATCH (c:Contract {{id:'{cid}'}}) MERGE (cl:Clause {{id:'{id}'}}) "
                 "SET cl.clause_type='{ct}', cl.text='{txt}' "
                 "MERGE (c)-[:CONTAINS]->(cl);".format(
                     cid=cl["contract_id"], id=cl["id"], ct=cl["clause_type"], txt=_q(cl["text"])))
    L.append("")

    for t in data["telemetry"]:
        L.append("MATCH (s:Supplier {{id:'{sid}'}}) MERGE (t:Telemetry {{id:'{id}'}}) "
                 "SET t.month='{m}', t.on_time_rate={otr}, t.incidents={inc} "
                 "MERGE (s)-[:HAS_TELEMETRY]->(t);".format(
                     sid=t["supplier_id"], id=t["id"], m=t["month"],
                     otr=t["on_time_rate"], inc=t["incidents"]))
    L.append("")

    for pd in data["policy_decisions"]:
        L.append("MATCH (c:Contract {{id:'{cid}'}}) MERGE (pd:PolicyDecision {{id:'{id}'}}) "
                 "SET pd.policy='{pol}', pd.outcome='{out}', pd.reason='{rsn}' "
                 "MERGE (pd)-[:APPLIED_TO]->(c);".format(
                     cid=pd["contract_id"], id=pd["id"], pol=pd["policy"], out=pd["outcome"],
                     rsn=_q(pd["reason"])))
    L.append("")
    path.write_text("\n".join(L) + "\n")


def main() -> None:
    data = build_dataset()
    write_csv(HERE / "suppliers.csv", data["suppliers"])
    write_csv(HERE / "contracts.csv", data["contracts"])
    write_csv(HERE / "contract_clauses.csv", data["contract_clauses"])
    write_csv(HERE / "consents.csv", data["consents"])
    write_csv(HERE / "telemetry.csv", data["telemetry"])
    (HERE / "fixtures.json").write_text(json.dumps(data, indent=2))
    write_cypher(SEED_CYPHER, data)

    pii = sum(1 for c in data["contracts"] if c["contains_pii"])
    q3_exposed = [c for c in data["contracts"]
                  if c["quarter"] == "FY26-Q3" and c["penalty_exposure"] > 1_000_000]
    at_risk = sum(1 for s in data["suppliers"] if s["delivery_at_risk"])
    print(f"suppliers={len(data['suppliers'])} contracts={len(data['contracts'])} "
          f"pii_contracts={pii} clauses={len(data['contract_clauses'])} "
          f"consents={len(data['consents'])} telemetry={len(data['telemetry'])}")
    print(f"§5: Q3 contracts with exposure>$1M = {len(q3_exposed)} "
          f"({sorted(c['supplier_id'] for c in q3_exposed)}); at_risk_suppliers={at_risk}")
    print(f"wrote CSVs + fixtures.json to {HERE}")
    print(f"wrote seed cypher to {SEED_CYPHER}")


if __name__ == "__main__":
    main()
