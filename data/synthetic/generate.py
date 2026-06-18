#!/usr/bin/env python3
"""Synthetic supplier-contract data generator. [spec §5.1, §5.2, §6]

Deterministic (fixed seed) so the worked use case in spec §6 always produces the same
outcome: among EMEA suppliers with PII contracts expiring before 2026-12-31, exactly
five have valid GDPR consent (shown), two have expired consent (masked), and one hosts
its data outside the EU (excluded). The remaining suppliers are filler that does *not*
match the worked-case filter, bringing totals to spec scale (~30 suppliers, ~80
contracts, ~15 with PII, ~10 with expired/missing consent).

Outputs:
  data/synthetic/suppliers.csv          ┐
  data/synthetic/contracts.csv          │ read by Cube via DuckDB (semantic layer)
  data/synthetic/contract_clauses.csv   │
  data/synthetic/consents.csv           ┘
  data/synthetic/fixtures.json          combined records (used by the test suite)
  services/context-graph/seed/load.cypher   Neo4j seed (context graph)

Run:  python data/synthetic/generate.py
"""
from __future__ import annotations

import csv
import json
import os
import random
from datetime import date, timedelta
from pathlib import Path

# Reference "as of" date — consent expiry is judged against this, baked in for
# determinism regardless of when the demo runs (matches the paper's scenario clock).
AS_OF = date(2026, 6, 18)
SEED = 20599942  # the paper's Zenodo record id, for a memorable deterministic seed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SEED_CYPHER = ROOT / "services" / "context-graph" / "seed" / "load.cypher"

# region -> (geo macro-region, default data residency)
REGIONS = {
    "EMEA-West": ("EMEA", "EU"),
    "EMEA-North": ("EMEA", "EU"),
    "UK": ("EMEA", "EU"),
    "US-East": ("AMER", "US"),
    "US-West": ("AMER", "US"),
    "APAC": ("APAC", "APAC"),
}
RISK_TIERS = ["low", "medium", "high", "critical"]


def _iso(d: date) -> str:
    return d.isoformat()


def build_dataset() -> dict:
    rng = random.Random(SEED)
    suppliers: list[dict] = []
    contracts: list[dict] = []
    clauses: list[dict] = []
    consents: list[dict] = []
    persons: list[dict] = []

    cid = 0  # contract counter
    clid = 0  # clause counter
    cnid = 0  # consent counter
    pid = 0  # person counter

    def add_contract(supplier_id, end_date, value, pii, secrets) -> dict:
        nonlocal cid, clid
        cid += 1
        c = {
            "id": f"CON-{cid:03d}",
            "supplier_id": supplier_id,
            "start_date": _iso(end_date - timedelta(days=rng.randint(365, 1095))),
            "end_date": _iso(end_date),
            "value_usd": value,
            "contains_pii": pii,
            "contains_secrets": secrets,
        }
        contracts.append(c)
        # Every contract has a standard clause; PII/secret contracts add the marked clause.
        clid += 1
        clauses.append({
            "id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "standard",
            "text": "Standard master services agreement terms and conditions apply.",
        })
        if pii:
            clid += 1
            clauses.append({
                "id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "pii",
                "text": ("Processor handles personal data of EU data subjects including "
                         "names, contact details and payroll identifiers."),
            })
        if secrets:
            clid += 1
            clauses.append({
                "id": f"CLA-{clid:03d}", "contract_id": c["id"], "clause_type": "secret",
                "text": ("CONFIDENTIAL: encryption key escrow procedure and root "
                         "credential rotation schedule (restricted)."),
            })
        return c

    def add_consent(supplier_id, status) -> dict:
        nonlocal cnid
        cnid += 1
        if status == "valid":
            retention = AS_OF + timedelta(days=rng.randint(120, 720))
        elif status == "expired":
            retention = AS_OF - timedelta(days=rng.randint(30, 365))
        else:  # missing — no consent row
            return None
        c = {
            "id": f"CNS-{cnid:03d}", "supplier_id": supplier_id,
            "granted_at": _iso(retention - timedelta(days=730)),
            "scope": "supplier_pii_processing",
            "retention_until": _iso(retention),
        }
        consents.append(c)
        return c

    def add_supplier(sid, name, region, residency, consent_status, risk) -> dict:
        nonlocal pid
        geo = REGIONS[region][0]
        s = {
            "id": sid, "name": name, "region": region, "geo": geo,
            "data_residency": residency, "gdpr_consent_status": consent_status,
            "risk_tier": risk,
        }
        suppliers.append(s)
        add_consent(sid, consent_status)
        # one data-subject Person per supplier (the consent covers them)
        pid += 1
        persons.append({"id": f"PER-{pid:03d}", "supplier_id": sid,
                        "name": f"Data Subject {pid}"})
        return s

    # ---------------------------------------------------------------- anchors (§6)
    # Five EMEA suppliers, EU-resident, PII contract expiring < 2026-12-31, valid
    # consent -> SHOWN. Ranked by contract value (descending) for the "top five".
    anchors_shown = [
        ("SUP-001", "Helvetia Pharma AG", "EMEA-West", date(2026, 6, 30), 9_800_000, "high"),
        ("SUP-002", "Nordic DataWorks AB", "EMEA-North", date(2026, 9, 15), 7_400_000, "high"),
        ("SUP-003", "Britannia Logistics Ltd", "UK", date(2026, 3, 1), 6_100_000, "medium"),
        ("SUP-004", "Rhein Components GmbH", "EMEA-West", date(2026, 11, 20), 5_250_000, "medium"),
        ("SUP-005", "Iberia Analytics SL", "EMEA-West", date(2026, 8, 10), 4_900_000, "critical"),
    ]
    for sid, name, region, end, val, risk in anchors_shown:
        add_supplier(sid, name, region, "EU", "valid", risk)
        add_contract(sid, end, val, pii=True, secrets=False)

    # Two EMEA suppliers with EXPIRED consent -> MASKED (allow_pii_field_access).
    for sid, name, region, end, val, risk in [
        ("SUP-006", "Baltic Cloud OU", "EMEA-North", date(2026, 5, 5), 8_300_000, "high"),
        ("SUP-007", "Gallia Secure SAS", "EMEA-West", date(2026, 7, 7), 6_750_000, "critical"),
    ]:
        add_supplier(sid, name, region, "EU", "expired", risk)
        add_contract(sid, end, val, pii=True, secrets=True)  # also has a secret clause

    # One EMEA supplier whose data is hosted in the US -> EXCLUDED (require_residency_match).
    add_supplier("SUP-008", "Albion Offshore Data Ltd", "UK", "US", "valid", "high")
    add_contract("SUP-008", date(2026, 4, 4), 7_900_000, pii=True, secrets=False)

    # ---------------------------------------------------------------- filler (~22)
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
        # Filler consent is mostly valid, sometimes expired/missing (to hit ~10 total).
        consent_status = rng.choices(["valid", "expired", "missing"], weights=[7, 2, 1])[0]
        risk = rng.choice(RISK_TIERS)
        add_supplier(sid, name, region, residency, consent_status, risk)
        for _ in range(rng.randint(2, 5)):
            # Most filler contracts expire after 2026 or carry no PII, so they do not
            # collide with the worked-case filter.
            end = AS_OF + timedelta(days=rng.randint(30, 1400))
            pii = rng.random() < 0.12  # keep total PII contracts near ~15
            secrets = rng.random() < 0.18
            value = rng.randint(2, 95) * 100_000
            add_contract(sid, end, value, pii=pii, secrets=secrets)

    # Seed a few historical PolicyDecision provenance nodes for the masked/excluded
    # anchors, so the graph shows policy decisions were previously applied (spec §5.2).
    policy_decisions = [
        {"id": "PDC-001", "policy": "allow_pii_field_access", "outcome": "mask",
         "contract_id": "CON-006", "reason": "consent expired"},
        {"id": "PDC-002", "policy": "allow_pii_field_access", "outcome": "mask",
         "contract_id": "CON-007", "reason": "consent expired"},
        {"id": "PDC-003", "policy": "require_residency_match", "outcome": "deny",
         "contract_id": "CON-008", "reason": "data hosted outside EU"},
    ]

    return {
        "as_of": _iso(AS_OF),
        "suppliers": suppliers,
        "contracts": contracts,
        "contract_clauses": clauses,
        "consents": consents,
        "persons": persons,
        "policy_decisions": policy_decisions,
    }


# --------------------------------------------------------------------------- writers
def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _q(s: str) -> str:
    """Escape a string for a single-quoted Cypher literal."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def write_cypher(path: Path, data: dict) -> None:
    L: list[str] = []
    L.append("// VCL context-graph seed — generated by data/synthetic/generate.py")
    L.append("// Do not edit by hand; rerun the generator to regenerate.")
    L.append("CREATE CONSTRAINT supplier_id IF NOT EXISTS FOR (s:Supplier) REQUIRE s.id IS UNIQUE;")
    L.append("CREATE CONSTRAINT contract_id IF NOT EXISTS FOR (c:Contract) REQUIRE c.id IS UNIQUE;")
    L.append("")

    # Regions
    geos = {}
    for region, (geo, _res) in REGIONS.items():
        geos.setdefault(region, geo)
        L.append(f"MERGE (:Region {{name:'{region}', geo:'{geo}'}});")
    L.append("")

    # Suppliers + OPERATES_IN + Person data subjects
    for s in data["suppliers"]:
        L.append(
            "MERGE (s:Supplier {{id:'{id}'}}) SET s.name='{name}', s.region='{region}', "
            "s.geo='{geo}', s.data_residency='{res}', s.gdpr_consent_status='{cs}', "
            "s.risk_tier='{rt}' "
            "WITH s MATCH (r:Region {{name:'{region}'}}) MERGE (s)-[:OPERATES_IN]->(r);".format(
                id=s["id"], name=_q(s["name"]), region=s["region"], geo=s["geo"],
                res=s["data_residency"], cs=s["gdpr_consent_status"], rt=s["risk_tier"],
            )
        )
    L.append("")
    for p in data["persons"]:
        L.append(
            "MATCH (s:Supplier {{id:'{sid}'}}) MERGE (p:Person {{id:'{id}'}}) "
            "SET p.name='{name}' MERGE (s)-[:HAS_DATA_SUBJECT]->(p);".format(
                sid=p["supplier_id"], id=p["id"], name=_q(p["name"]))
        )
    L.append("")

    # Consents
    for c in data["consents"]:
        L.append(
            "MATCH (s:Supplier {{id:'{sid}'}}) MERGE (cn:Consent {{id:'{id}'}}) "
            "SET cn.granted_at=date('{g}'), cn.scope='{scope}', "
            "cn.retention_until=date('{r}') MERGE (s)-[:HAS_CONSENT]->(cn);".format(
                sid=c["supplier_id"], id=c["id"], g=c["granted_at"], scope=c["scope"],
                r=c["retention_until"])
        )
    L.append("")

    # Contracts + BELONGS_TO
    for c in data["contracts"]:
        L.append(
            "MATCH (s:Supplier {{id:'{sid}'}}) MERGE (c:Contract {{id:'{id}'}}) "
            "SET c.start_date=date('{sd}'), c.end_date=date('{ed}'), "
            "c.value_usd={val}, c.contains_pii={pii}, c.contains_secrets={sec} "
            "MERGE (c)-[:BELONGS_TO]->(s);".format(
                sid=c["supplier_id"], id=c["id"], sd=c["start_date"], ed=c["end_date"],
                val=c["value_usd"], pii=str(c["contains_pii"]).lower(),
                sec=str(c["contains_secrets"]).lower())
        )
    L.append("")

    # Clauses + CONTAINS
    for cl in data["contract_clauses"]:
        L.append(
            "MATCH (c:Contract {{id:'{cid}'}}) MERGE (cl:Clause {{id:'{id}'}}) "
            "SET cl.clause_type='{ct}', cl.text='{txt}' "
            "MERGE (c)-[:CONTAINS]->(cl);".format(
                cid=cl["contract_id"], id=cl["id"], ct=cl["clause_type"],
                txt=_q(cl["text"]))
        )
    L.append("")

    # PolicyDecision provenance + APPLIED_TO
    for pd in data["policy_decisions"]:
        L.append(
            "MATCH (c:Contract {{id:'{cid}'}}) MERGE (pd:PolicyDecision {{id:'{id}'}}) "
            "SET pd.policy='{pol}', pd.outcome='{out}', pd.reason='{rsn}' "
            "MERGE (pd)-[:APPLIED_TO]->(c);".format(
                cid=pd["contract_id"], id=pd["id"], pol=pd["policy"], out=pd["outcome"],
                rsn=_q(pd["reason"]))
        )
    L.append("")
    return path.write_text("\n".join(L) + "\n")


def main() -> None:
    data = build_dataset()

    write_csv(HERE / "suppliers.csv", data["suppliers"])
    write_csv(HERE / "contracts.csv", data["contracts"])
    write_csv(HERE / "contract_clauses.csv", data["contract_clauses"])
    write_csv(HERE / "consents.csv", data["consents"])
    (HERE / "fixtures.json").write_text(json.dumps(data, indent=2))
    write_cypher(SEED_CYPHER, data)

    # Summary
    pii = sum(1 for c in data["contracts"] if c["contains_pii"])
    bad_consent = sum(1 for s in data["suppliers"]
                      if s["gdpr_consent_status"] in ("expired", "missing"))
    print(f"suppliers={len(data['suppliers'])} contracts={len(data['contracts'])} "
          f"pii_contracts={pii} clauses={len(data['contract_clauses'])} "
          f"consents={len(data['consents'])} bad_consent_suppliers={bad_consent}")
    print(f"wrote CSVs + fixtures.json to {HERE}")
    print(f"wrote seed cypher to {SEED_CYPHER}")


if __name__ == "__main__":
    main()
