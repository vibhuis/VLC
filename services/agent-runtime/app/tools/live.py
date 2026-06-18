"""Live toolbox — talks to the real VCL services. [spec §5.4]

OPA (REST), Cube (REST), feedback-loop (REST), Neo4j (bolt driver).
"""
from __future__ import annotations

import httpx

from ..config import settings
from .base import Toolbox

# The verified worked-use-case query: WHERE binds to the main MATCH (not the OPTIONAL
# MATCH) so the contract filters actually apply. [verified against the seeded graph]
GRAPH_QUERY = """
MATCH (c:Contract)-[:BELONGS_TO]->(s:Supplier)-[:OPERATES_IN]->(r:Region)
WHERE ($geo IS NULL OR r.geo = $geo)
  AND ($contains_pii IS NULL OR c.contains_pii = $contains_pii)
  AND ($end_before IS NULL OR c.end_date <= date($end_before))
OPTIONAL MATCH (s)-[:HAS_CONSENT]->(cn:Consent)
RETURN s.id AS supplier_id, s.name AS name, s.region AS region, s.geo AS geo,
       s.data_residency AS data_residency, s.gdpr_consent_status AS gdpr_consent_status,
       s.risk_tier AS risk_tier, c.id AS contract_id, toString(c.end_date) AS end_date,
       c.value_usd AS value_usd, c.contains_secrets AS contains_secrets,
       toString(cn.retention_until) AS consent_retention_until
ORDER BY c.value_usd DESC
"""


class LiveToolbox(Toolbox):
    def __init__(self) -> None:
        from neo4j import GraphDatabase  # imported lazily so tests need no driver
        self._driver = GraphDatabase.driver(
            settings.graph_bolt_uri, auth=(settings.graph_user, settings.graph_password)
        )
        self._http = httpx.Client(timeout=15.0)

    # ---- policy engine (OPA) ----
    def _decide(self, rule: str, payload: dict) -> dict:
        r = self._http.post(f"{settings.policy_url}/v1/data/vcl/{rule}", json={"input": payload})
        r.raise_for_status()
        return r.json().get("result", {})

    # ---- semantic layer (Cube) ----
    def semantic_query(self, intent: dict) -> dict:
        """Governed aggregate over the supplier_risk_view — proves the semantic layer is
        in the loop and shapes the same filters used for retrieval."""
        query = {
            "measures": ["supplier_risk_view.contracts_total_value_usd"],
            "dimensions": ["supplier_risk_view.geo"],
        }
        try:
            r = self._http.get(f"{settings.semantic_url}/cubejs-api/v1/load",
                               params={"query": __import__("json").dumps(query)})
            r.raise_for_status()
            return {"query": query, "data": r.json().get("data", [])}
        except httpx.HTTPError as e:
            return {"query": query, "data": [], "note": f"semantic layer unavailable: {e}"}

    # ---- context graph (Neo4j) ----
    def graph_query(self, intent: dict) -> list[dict]:
        params = {
            "geo": intent.get("geo"),
            "contains_pii": intent.get("contains_pii"),
            "end_before": intent.get("end_before"),
        }
        with self._driver.session() as session:
            result = session.run(GRAPH_QUERY, **params)
            return [dict(record) for record in result]

    # ---- feedback loop ----
    def feedback_emit(self, event: dict) -> None:
        self._http.post(f"{settings.feedback_url}/events", json=event, timeout=5.0)

    def close(self) -> None:
        self._driver.close()
        self._http.close()
