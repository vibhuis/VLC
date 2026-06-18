"""LangGraph state machine — the governed reasoning loop. [spec §5.4]

    [receive] → [parse intent] → [policy precheck] ─deny→ [decline+audit] → END
                                      │allow
                                      ▼
              [plan] → [run graph + semantic queries] → [per-row policy filter]
                       → [synthesise] → [emit final audit] → END

Every node emits a trace event through the AuditEmitter, so the feedback loop captures
the full decision path. The Toolbox (live or fixture) is injected, so the same graph runs
against the real stack or deterministic fixtures.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .audit import AuditEmitter
from .config import settings
from .llm import synthesize
from .tools.base import Toolbox


class VclState(TypedDict, total=False):
    query: str
    principal: dict
    intent: dict
    precheck: dict
    candidates: list
    filtered: dict
    answer: str
    decisions: list
    declined: bool
    llm_mode: str


def build_graph(toolbox: Toolbox, audit: AuditEmitter):
    principal = audit.principal

    def parse_intent(state: VclState) -> VclState:
        intent = toolbox.parse(state["query"])
        audit.emit("semantic_layer", "parse_intent",
                   input={"query": state["query"]}, output={"intent": intent})
        return {"intent": intent}

    def policy_precheck(state: VclState) -> VclState:
        intent = state["intent"]
        decision = toolbox.policy_check(
            "query_supplier_pii_intersection", principal, {"geo": intent.get("geo")})
        audit.emit("policy_engine", "precheck_allow_supplier_query",
                   input={"action": "query_supplier_pii_intersection",
                          "resource": {"geo": intent.get("geo")}},
                   output={"allow": decision.get("allow")},
                   policy_decisions=[decision])
        return {"precheck": decision, "declined": not decision.get("allow", False)}

    def decline(state: VclState) -> VclState:
        reasons = state["precheck"].get("reasons", [])
        audit.emit("agent", "decline",
                   output={"answer": "Request declined by policy."},
                   policy_decisions=[state["precheck"]])
        return {"answer": "Request declined by policy: " + "; ".join(reasons),
                "decisions": [state["precheck"]]}

    def plan(state: VclState) -> VclState:
        audit.emit("agent", "plan_queries",
                   output={"plan": "retrieve EMEA PII contracts in range from the context "
                                   "graph; aggregate via the semantic layer; per-row policy filter"})
        return {}

    def run_queries(state: VclState) -> VclState:
        intent = state["intent"]
        sem = toolbox.semantic_query(intent)
        audit.emit("semantic_layer", "governed_query",
                   input={"intent": intent}, output={"semantic_result": sem})
        rows = toolbox.graph_query(intent)
        audit.emit("context_graph", "query_supplier_contracts",
                   input={"filters": {k: intent.get(k) for k in ("geo", "contains_pii", "end_before")}},
                   output={"row_count": len(rows),
                           "supplier_ids": [r["supplier_id"] for r in rows]})
        return {"candidates": rows}

    def policy_filter(state: VclState) -> VclState:
        result = toolbox.policy_filter(state["candidates"], principal, state["intent"], settings.as_of)
        audit.emit("policy_engine", "per_row_filter",
                   input={"candidate_count": len(state["candidates"])},
                   output={"allowed": len(result["allowed"]), "masked": len(result["masked"]),
                           "excluded": len(result["excluded"])},
                   policy_decisions=result["decisions"])
        return {"filtered": result, "decisions": result["decisions"]}

    def synth(state: VclState) -> VclState:
        f = state["filtered"]
        limit = state["intent"].get("limit") or 5
        answer, mode = synthesize(state["query"], f["allowed"], f["masked"], f["excluded"], limit)
        audit.emit("response", "synthesise_response",
                   input={"allowed": len(f["allowed"]), "masked": len(f["masked"]),
                          "excluded": len(f["excluded"]), "llm_mode": mode},
                   output={"answer": answer})
        return {"answer": answer, "llm_mode": mode}

    def final_audit(state: VclState) -> VclState:
        audit.emit("agent", "emit_final_audit",
                   output={"trace_id": audit.trace_id, "decision_count": len(state.get("decisions", []))})
        return {}

    g = StateGraph(VclState)
    g.add_node("parse_intent", parse_intent)
    g.add_node("policy_precheck", policy_precheck)
    g.add_node("decline", decline)
    g.add_node("plan", plan)
    g.add_node("run_queries", run_queries)
    g.add_node("policy_filter", policy_filter)
    g.add_node("synth", synth)
    g.add_node("final_audit", final_audit)

    g.add_edge(START, "parse_intent")
    g.add_edge("parse_intent", "policy_precheck")
    g.add_conditional_edges("policy_precheck", lambda s: "decline" if s.get("declined") else "plan",
                            {"decline": "decline", "plan": "plan"})
    g.add_edge("decline", END)
    g.add_edge("plan", "run_queries")
    g.add_edge("run_queries", "policy_filter")
    g.add_edge("policy_filter", "synth")
    g.add_edge("synth", "final_audit")
    g.add_edge("final_audit", END)
    return g.compile()


def run_query(query: str, toolbox: Toolbox, principal: dict) -> dict:
    """Execute one query end-to-end and return {answer, trace_id, decisions, events, ...}."""
    audit = AuditEmitter(sink=toolbox.feedback_emit, principal=principal)
    graph = build_graph(toolbox, audit)
    final = graph.invoke({"query": query, "principal": principal})
    return {
        "answer": final.get("answer", ""),
        "trace_id": audit.trace_id,
        "decisions": final.get("decisions", []),
        "events": audit.events,
        "llm_mode": final.get("llm_mode", "n/a"),
        "filtered": final.get("filtered", {}),
    }
