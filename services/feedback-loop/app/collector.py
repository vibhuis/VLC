"""Feedback loop — capture, persist and replay every decision. [spec §5.5]

OpenTelemetry-shaped trace events are persisted to a local SQLite database
(``data/audit.sqlite``), indexed by ``trace_id``. The agent runtime POSTs one event per
pipeline step; the UI and any auditor read the full ordered trace back via
``GET /trace/{trace_id}``.

The event schema matches spec §5.5 exactly:

    {trace_id, step_id, timestamp, component, action, principal, input, output,
     policy_decisions[], regulatory_mapping{eu_ai_act_articles[], nist_rmf_functions[]}}
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("VCL_AUDIT_DB", "data/audit.sqlite")

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
                payload    TEXT NOT NULL
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_trace ON trace_events(trace_id)")


@app.on_event("startup")
def _startup() -> None:
    _init_db()


# --------------------------------------------------------------------------- routes
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/events")
def ingest(event: TraceEvent) -> dict:
    """Persist a single trace event. Returns the trace_id it was filed under."""
    with _conn() as con:
        con.execute(
            "INSERT INTO trace_events (trace_id, step_id, timestamp, component, action, payload)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.trace_id,
                event.step_id,
                event.timestamp,
                event.component,
                event.action,
                event.model_dump_json(),
            ),
        )
    return {"trace_id": event.trace_id, "step_id": event.step_id}


@app.get("/trace/{trace_id}")
def get_trace(trace_id: str) -> dict:
    """Return the full ordered list of events for a trace (spec §5.5 interface)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT payload FROM trace_events WHERE trace_id = ? ORDER BY row_id ASC",
            (trace_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail=f"trace {trace_id} not found")
    events = [json.loads(r["payload"]) for r in rows]
    return {"trace_id": trace_id, "event_count": len(events), "events": events}


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
