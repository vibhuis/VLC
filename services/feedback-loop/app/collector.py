"""Feedback loop — capture, persist, replay, and *verify* every decision. [spec §5.5; paper §4.2, §6.1]

OpenTelemetry-shaped trace events are persisted to a local SQLite database
(``data/audit.sqlite``), indexed by ``trace_id``. The agent runtime POSTs one event per
pipeline step; the UI and any auditor read the full ordered trace back via
``GET /trace/{trace_id}``.

Verifiability (the paper's load-bearing property, §6.1): each event is **hash-chained** to
the previous one with an HMAC keyed by a server secret — a tamper-evident transparency log
in the spirit of MAIF cryptographic provenance [39] and PROV-AGENT [40]. ``GET /verify``
re-derives the chain and reports whether it is intact; ``GET /prov`` exports the trace as a
W3C PROV / PROV-AGENT-shaped document. Editing any persisted event without the key breaks
the chain and ``/verify`` flags it.

Event schema (spec §5.5):
    {trace_id, step_id, timestamp, component, action, principal, input, output,
     policy_decisions[], regulatory_mapping{eu_ai_act_articles[], nist_rmf_functions[]}}
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("VCL_AUDIT_DB", "data/audit.sqlite")
# Server-held key for the tamper-evident audit chain. Override in production.
HMAC_KEY = os.environ.get("VCL_AUDIT_HMAC_KEY", "vcl-demo-audit-key").encode()
GENESIS = "0" * 64

app = FastAPI(title="VCL Feedback Loop", version="0.1.0")


# --------------------------------------------------------------------------- schema
class PolicyDecision(BaseModel):
    policy: str
    outcome: str  # allow | deny | mask
    reasons: list[str] = Field(default_factory=list)


class RegulatoryMapping(BaseModel):
    eu_ai_act_articles: list[str] = Field(default_factory=list)
    nist_rmf_functions: list[str] = Field(default_factory=list)


class TraceEvent(BaseModel):
    trace_id: str
    step_id: str
    timestamp: str
    component: str  # semantic_layer|context_graph|policy_engine|agent|response
    action: str
    principal: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    regulatory_mapping: RegulatoryMapping = Field(default_factory=RegulatoryMapping)


def chain_hash(prev_hash: str, payload: str) -> str:
    """HMAC-SHA256 over (previous hash ++ canonical payload) — one link of the audit chain."""
    return hmac.new(HMAC_KEY, (prev_hash + payload).encode(), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------- storage
@contextmanager
def _conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def _init_db() -> None:
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS trace_events (
                row_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id   TEXT NOT NULL,
                step_id    TEXT NOT NULL,
                timestamp  TEXT NOT NULL,
                component  TEXT NOT NULL,
                action     TEXT NOT NULL,
                payload    TEXT NOT NULL,
                prev_hash  TEXT NOT NULL DEFAULT '',
                entry_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_trace ON trace_events(trace_id)")
        # Migrate older databases that predate the hash-chain columns.
        cols = {r["name"] for r in con.execute("PRAGMA table_info(trace_events)")}
        if "prev_hash" not in cols:
            con.execute("ALTER TABLE trace_events ADD COLUMN prev_hash TEXT NOT NULL DEFAULT ''")
        if "entry_hash" not in cols:
            con.execute("ALTER TABLE trace_events ADD COLUMN entry_hash TEXT NOT NULL DEFAULT ''")


@app.on_event("startup")
def _startup() -> None:
    _init_db()


# --------------------------------------------------------------------------- routes
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/events")
def ingest(event: TraceEvent) -> dict:
    """Persist one trace event, linking it into the per-trace tamper-evident hash chain."""
    payload = event.model_dump_json()
    with _conn() as con:
        last = con.execute(
            "SELECT entry_hash FROM trace_events WHERE trace_id = ? ORDER BY row_id DESC LIMIT 1",
            (event.trace_id,),
        ).fetchone()
        prev_hash = last["entry_hash"] if last else GENESIS
        entry_hash = chain_hash(prev_hash, payload)
        con.execute(
            "INSERT INTO trace_events (trace_id, step_id, timestamp, component, action,"
            " payload, prev_hash, entry_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (event.trace_id, event.step_id, event.timestamp, event.component,
             event.action, payload, prev_hash, entry_hash),
        )
    return {"trace_id": event.trace_id, "step_id": event.step_id, "entry_hash": entry_hash}


def _rows(trace_id: str) -> list[sqlite3.Row]:
    with _conn() as con:
        return con.execute(
            "SELECT payload, prev_hash, entry_hash FROM trace_events "
            "WHERE trace_id = ? ORDER BY row_id ASC",
            (trace_id,),
        ).fetchall()


@app.get("/trace/{trace_id}")
def get_trace(trace_id: str) -> dict:
    """Return the full ordered list of events for a trace, with chain integrity. [spec §5.5]"""
    rows = _rows(trace_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    events = []
    for r in rows:
        ev = json.loads(r["payload"])
        ev["_audit"] = {"prev_hash": r["prev_hash"], "entry_hash": r["entry_hash"]}
        events.append(ev)
    integrity = _verify_rows(rows)
    return {"trace_id": trace_id, "event_count": len(events),
            "head_hash": rows[-1]["entry_hash"], "integrity": integrity, "events": events}


def _verify_rows(rows: list[sqlite3.Row]) -> dict:
    prev = GENESIS
    for i, r in enumerate(rows):
        expected = chain_hash(prev, r["payload"])
        if expected != r["entry_hash"] or r["prev_hash"] != prev:
            return {"valid": False, "broken_at_step": i + 1, "steps": len(rows)}
        prev = r["entry_hash"]
    return {"valid": True, "broken_at_step": None, "steps": len(rows)}


@app.get("/verify/{trace_id}")
def verify(trace_id: str) -> dict:
    """Re-derive the hash chain and report whether the audit trail is intact (tamper-evident)."""
    rows = _rows(trace_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    result = _verify_rows(rows)
    result.update({"trace_id": trace_id, "head_hash": rows[-1]["entry_hash"]})
    return result


@app.get("/prov/{trace_id}")
def prov(trace_id: str) -> dict:
    """Export the trace as a W3C PROV / PROV-AGENT-shaped document. [paper §4.2, ref 40]

    Each pipeline step → a prov:Activity; the principal → a prov:Agent; each step's output →
    a prov:Entity wasGeneratedBy the activity and wasAttributedTo the agent. The hash chain
    is carried so the provenance document is itself verifiable.
    """
    rows = _rows(trace_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    events = [json.loads(r["payload"]) for r in rows]
    principal = events[0].get("principal", {})
    agent_id = f"agent:{principal.get('user', 'demo')}"
    doc: dict[str, Any] = {
        "prefix": {"vcl": "urn:vcl:", "prov": "http://www.w3.org/ns/prov#"},
        "agent": {agent_id: {"prov:type": "prov:SoftwareAgent",
                             "vcl:purpose": principal.get("purpose")}},
        "activity": {}, "entity": {}, "wasGeneratedBy": {}, "wasAssociatedWith": {},
        "used": {},
    }
    for i, (ev, r) in enumerate(zip(events, rows), 1):
        act = f"vcl:step{i}"
        ent = f"vcl:out{i}"
        doc["activity"][act] = {
            "prov:startTime": ev["timestamp"], "vcl:component": ev["component"],
            "vcl:action": ev["action"],
            "vcl:policy_decisions": [d.get("policy") for d in ev.get("policy_decisions", [])],
            "vcl:eu_ai_act_articles": ev["regulatory_mapping"]["eu_ai_act_articles"],
        }
        doc["entity"][ent] = {"vcl:output": ev.get("output", {}),
                              "vcl:entry_hash": r["entry_hash"]}
        doc["wasGeneratedBy"][f"_gen{i}"] = {"prov:entity": ent, "prov:activity": act}
        doc["wasAssociatedWith"][f"_assoc{i}"] = {"prov:activity": act, "prov:agent": agent_id}
        if i > 1:
            doc["used"][f"_used{i}"] = {"prov:activity": act, "prov:entity": f"vcl:out{i-1}"}
    doc["vcl:integrity"] = _verify_rows(rows)
    doc["vcl:head_hash"] = rows[-1]["entry_hash"]
    return {"trace_id": trace_id, "prov": doc}


@app.get("/traces")
def list_traces(limit: int = 50) -> dict:
    """List recent trace ids (newest first) — convenience for the UI."""
    with _conn() as con:
        rows = con.execute(
            """
            SELECT trace_id, MIN(timestamp) AS started, COUNT(*) AS steps
            FROM trace_events GROUP BY trace_id ORDER BY MAX(row_id) DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"traces": [dict(r) for r in rows]}
