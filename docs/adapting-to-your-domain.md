# Adapting the VCL to your domain

This is a **reference implementation**, not a turnkey product (see [DECISIONS.md](../DECISIONS.md)
§1.2). The engine — the LangGraph pipeline, the tamper-evident audit log, the MCP gateway,
the policy engine, the feedback loop — is domain-agnostic. The *business* part (your
entities, metrics, policies, and how a question maps to them) lives behind a small set of
extension points. This guide walks them in order.

The shipped demo answers supplier-risk questions over synthetic data. To answer questions
over **your** data you change six things, roughly in this order.

---

## 0. The shape of a request (so the steps make sense)

```
question ──▶ Scenario.detect/parse ──▶ policy precheck ──▶ Scenario data query
         ──▶ Scenario.policy_filter (OPA) ──▶ Scenario.synthesize ──▶ tamper-evident trace
```

Everything except the four `Scenario.*` methods and the data behind them is reusable as-is.

---

## 1. Model your data

Replace the synthetic generator with your own. The demo's
[`data/synthetic/generate.py`](../data/synthetic/generate.py) emits:

- CSVs read by the semantic layer (Cube via DuckDB), and
- a Neo4j `load.cypher` for the context graph, and
- a `fixtures.json` used by the hermetic tests.

For your domain, produce the equivalent for your entities (the demo has suppliers,
contracts, clauses, consents, telemetry). Keep one **canonical id** per entity so the graph
can resolve cross-system references. If you have real sources, point the loaders at them
instead (see the optional Postgres profile in the README, and the roadmap for connectors).

## 2. Define the semantic layer (Cube)

Edit [`services/semantic-layer/model/`](../services/semantic-layer/model/): one cube per
entity (dimensions + measures), plus a `view` that joins them — your **grounding contract**.
Derived metrics go here (the demo's `penalty_exposure` and `avg_delivery_risk_score` are
examples). This is what the paper calls the type-contract the agent resolves against.

## 3. Seed the context graph (Neo4j)

The generator writes `services/context-graph/seed/load.cypher`. Model your nodes, your
relationships, and your **provenance** — including cross-system identity resolution
(`(:SystemRef)-[:RESOLVES_TO]->(:Entity)` in the demo) and any `PolicyDecision` provenance
you want to pre-seed. The container re-seeds on first start.

## 4. Write your policies (OPA / Rego)

Edit [`services/policy-engine/policies/vcl.rego`](../services/policy-engine/policies/vcl.rego).
Each policy returns a structured decision:

```rego
my_policy := {"policy": "my_policy", "allow": <bool>, "outcome": "allow"|"deny"|"mask",
              "reasons": [<str>]}
```

Add a unit test in `vcl_test.rego` (run `opa test services/policy-engine/policies`) and, if
you want the hermetic Python tests to keep working, mirror the rule in
[`FixtureToolbox._decide`](../services/agent-runtime/app/tools/fixtures.py) — the
`test_policy_parity` suite asserts the mirror matches live OPA, so it can't drift.

## 5. Add a Scenario (the core extension point)

Create `services/agent-runtime/app/scenarios/<your_scenario>.py` subclassing
[`Scenario`](../services/agent-runtime/app/scenarios/base.py) and implement four methods:

```python
class MyScenario(Scenario):
    name = "my_scenario"
    label = "My domain — what it answers"
    sample_query = "A question a user would type."

    def detect(self, q_lower: str) -> bool:
        # return True if this scenario should handle the query (keyword/regex match)
        ...

    def parse(self, query: str, intent: dict) -> None:
        # extract the structured fields your query needs onto `intent`
        ...

    def policy_filter(self, toolbox, rows, principal, intent, as_of) -> dict:
        # call toolbox._decide("<rule>", {...}) per row; return
        # {"allowed": [...], "masked": [...], "excluded": [...], "decisions": [...]}
        ...

    def synthesize(self, intent, filtered, limit) -> tuple[str, str]:
        # return (answer_text, mode); use the deterministic path + an optional LLM path
        ...
```

Register it in
[`app/scenarios/__init__.py`](../services/agent-runtime/app/scenarios/__init__.py)
(order = detection precedence). Look at `penalty_delivery.py` and `supplier_pii.py` as
worked examples.

## 6. Wire the data retrieval

Your scenario's rows come from the toolboxes. Add a branch (keyed on `intent["scenario"]`)
in:

- [`LiveToolbox.graph_query`](../services/agent-runtime/app/tools/live.py) — a Cypher query
  against Neo4j (and, if relevant, `semantic_query` against Cube), and
- [`FixtureToolbox.graph_query`](../services/agent-runtime/app/tools/fixtures.py) — the same
  shape over `fixtures.json`, so the hermetic tests run without the stack.

The MCP gateway exposes these automatically — no change needed.

---

## 7. Test it

```bash
uv run ruff check services data scripts
opa test services/policy-engine/policies            # your Rego unit tests
uv run pytest -q                                    # hermetic; add a tests/test_<scenario>.py
docker compose up -d --build && python scripts/smoke.py   # live end-to-end
```

Add a hermetic acceptance test modelled on
[`test_worked_use_case_paper.py`](../services/agent-runtime/tests/test_worked_use_case_paper.py):
assert which entities are shown / masked / excluded and which policies fired.

---

## What you get for free

Once your scenario returns rows and decisions, the platform gives you — with no extra work —
the governed pipeline, the **tamper-evident** hash-chained audit log (`/verify`), the W3C
PROV export (`/prov`), the EU AI Act / NIST regulatory mapping, the MCP tool surface, the
Streamlit trace viewer, and the PDF compliance report. That reuse is the point of the VCL
pattern: you bring the domain; the verifiability is the substrate.
