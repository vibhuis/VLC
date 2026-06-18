"""Agent runtime — FastAPI surface. [spec §5.4]

POST /query  → {answer, trace_id, decisions}
GET  /trace/{trace_id} → proxied from the feedback loop for convenience
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import settings
from .graph import run_query
from .tools.live import LiveToolbox

app = FastAPI(title="VCL Agent Runtime", version="0.1.0")

_toolbox: LiveToolbox | None = None


def get_toolbox() -> LiveToolbox:
    global _toolbox
    if _toolbox is None:
        _toolbox = LiveToolbox()
    return _toolbox


def demo_principal() -> dict:
    # Single demo user (no auth in this MVP — spec §9). Has org access to all geos; the
    # residency and consent policies still constrain individual rows.
    return {"user": settings.demo_user, "purpose": settings.demo_purpose,
            "org_access": ["EMEA", "AMER", "APAC"]}


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    trace_id: str
    decisions: list[dict]
    llm_mode: str


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "llm_enabled": settings.llm_enabled}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    result = run_query(req.query, get_toolbox(), demo_principal())
    return QueryResponse(answer=result["answer"], trace_id=result["trace_id"],
                         decisions=result["decisions"], llm_mode=result["llm_mode"])


@app.get("/trace/{trace_id}")
def trace(trace_id: str) -> dict:
    try:
        r = httpx.get(f"{settings.feedback_url}/trace/{trace_id}", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail="trace not found") from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"feedback loop unavailable: {e}") from e
