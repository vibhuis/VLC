"""Trace emission — every pipeline step becomes a structured audit event. [spec §5.5]

Events are built to the spec §5.5 schema (including the regulatory_mapping that ties each
step to EU AI Act articles and NIST AI RMF functions) and handed to a sink callable
(the feedback-loop client). The regulatory mapping is what makes the trace
"regulator-addressable": the compliance report reads these fields back out.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

# Which regulatory obligations each pipeline step evidences. [spec §5.5, §8]
# EU AI Act: Art. 9 = risk management, Art. 10 = data governance,
# Art. 12 = record-keeping/logging, Art. 13 = transparency.
# NIST AI RMF functions: GOVERN / MAP / MEASURE / MANAGE.
REGULATORY_MAP: dict[str, dict[str, list[str]]] = {
    "semantic_layer": {"eu_ai_act_articles": ["12"], "nist_rmf_functions": ["MAP-3.4"]},
    "context_graph": {"eu_ai_act_articles": ["10", "12"], "nist_rmf_functions": ["MAP-2.3"]},
    "policy_engine": {"eu_ai_act_articles": ["9", "12"], "nist_rmf_functions": ["MEASURE-2.7", "GOVERN-1.2"]},
    "agent": {"eu_ai_act_articles": ["12", "13", "14"], "nist_rmf_functions": ["MANAGE-2.2"]},
    "response": {"eu_ai_act_articles": ["12", "13"], "nist_rmf_functions": ["MEASURE-2.7"]},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditEmitter:
    """Builds and emits trace events for one query (one ``trace_id``)."""

    def __init__(self, sink: Callable[[dict], Any], principal: dict, trace_id: str | None = None):
        self.trace_id = trace_id or str(uuid.uuid4())
        self.sink = sink
        self.principal = principal
        self.events: list[dict] = []

    def emit(
        self,
        component: str,
        action: str,
        *,
        input: dict | None = None,
        output: dict | None = None,
        policy_decisions: list[dict] | None = None,
    ) -> dict:
        mapping = REGULATORY_MAP.get(component, {"eu_ai_act_articles": [], "nist_rmf_functions": []})
        event = {
            "trace_id": self.trace_id,
            "step_id": str(uuid.uuid4()),
            "timestamp": _now(),
            "component": component,
            "action": action,
            "principal": self.principal,
            "input": input or {},
            "output": output or {},
            "policy_decisions": policy_decisions or [],
            "regulatory_mapping": mapping,
        }
        self.events.append(event)
        try:
            self.sink(event)
        except Exception:  # tracing must never break the request path
            pass
        return event
