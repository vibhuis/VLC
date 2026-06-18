"""Agent runtime — FastAPI surface. [spec §5.4]

Phase 1: health + a stub /query so the service starts and the stack comes up.
Phase 4/5 replace the stub with the LangGraph state machine.
"""
from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="VCL Agent Runtime", version="0.1.0")


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    trace_id: str
    decisions: list[dict]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "phase": 1}


@app.post("/query", response_model=QueryResponse)
def query(_: QueryRequest) -> QueryResponse:
    # Stub — replaced by the LangGraph pipeline in Phase 4/5.
    return QueryResponse(
        answer="VCL prototype — Phase 1 stub. Agent pipeline not yet wired.",
        trace_id="00000000-0000-0000-0000-000000000000",
        decisions=[],
    )
