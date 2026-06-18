# VCL Reference Implementation — Build Specification

**Project codename:** `vcl-ref-impl`
**Author of spec:** Vibhuraja Bhutani
**Date:** 8 June 2026
**Intended builder:** Claude Code (autonomous coding agent)
**Companion paper:** *The Verifiable Context Layer*, Zenodo DOI `10.5281/zenodo.20599942`
**Target outcome:** A working end-to-end demonstration of the five-component VCL pattern, runnable locally via Docker Compose, that produces a regulator-addressable audit trail for the worked use case in Section 5 of the paper.

---

## 1. Project Goals

### 1.1 What this prototype must prove

The paper claims that the five VCL components — semantic layer, context graph, policy engine, agent runtime, feedback loop — when composed, produce **verifiable enterprise AI** with a regulator-addressable audit trail. This prototype must demonstrate that claim concretely. Specifically:

1. **An agent answers a real enterprise question** (the Section 5 worked use case: a supplier-contract query).
2. **Every step is governed** by an explicit policy enforced at runtime, not after the fact.
3. **Every step is traced** with sufficient detail that a hypothetical auditor could replay the decision.
4. **Trust assertions are demonstrable**: e.g., "this answer used only data subject to EU-residency consent" can be proven from the trace.

### 1.2 What this prototype is not

- Not a production system. No high-availability, no horizontal scaling, no enterprise integration.
- Not a research validation experiment with statistical claims. (That follows in a later study.)
- Not a polished product. UI is functional, not pretty.
- Not multi-tenant. Single demo user.
- Not connected to a real enterprise dataset. Synthetic data only.

### 1.3 Success criteria

The prototype is **done** when an unaffiliated reviewer can:

1. Clone the repo, run `docker compose up`, wait < 5 minutes.
2. Open a browser to `localhost:8501`, type the worked-use-case query.
3. See the agent produce a correct answer.
4. Click "Show audit trace" and see the full step-by-step decision path: semantic query → graph traversal → policy checks → agent reasoning → response synthesis.
5. Click "Export compliance report" and download a PDF that maps the trace to EU AI Act Articles 9, 12, 13, and NIST AI RMF functions.

If a reviewer can do all five of those without my help, the MVP is shipped.

---

## 2. Architecture

The prototype implements Figure 3 of the paper (the VCL reference architecture). Five components, each a separate service in a single Docker Compose stack.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         USER (browser)                                │
│                            │                                          │
│                            ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Streamlit UI (port 8501)                                       │  │
│  │  - Query input                                                  │  │
│  │  - Response display                                             │  │
│  │  - Audit trace viewer                                           │  │
│  │  - Compliance report export                                     │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                            │                                          │
│                            ▼                                          │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  Agent Runtime  (FastAPI, port 8000)                            │  │
│  │  LangGraph-based reasoning loop                                 │  │
│  │  Anthropic Claude API as the LLM backbone                       │  │
│  └────────────────────────────────────────────────────────────────┘  │
│           │                  │                 │             │        │
│           ▼                  ▼                 ▼             ▼        │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │  Semantic    │  │  Context Graph │  │   Policy    │  │ Feedback │ │
│  │  Layer       │  │                │  │   Engine    │  │  Loop    │ │
│  │  Cube.dev    │  │  Neo4j         │  │  Open       │  │ OTel +   │ │
│  │              │  │                │  │  Policy     │  │ JSON     │ │
│  │  port 4000   │  │  port 7687     │  │  Agent      │  │ audit    │ │
│  │              │  │                │  │  port 8181  │  │ store    │ │
│  └──────────────┘  └────────────────┘  └─────────────┘  └──────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. Tech Stack

All choices favour **local-first, open-source, fast-to-demo** over production-grade. Claude Code may substitute any component for a better-fit equivalent provided the substitution is justified in a `DECISIONS.md` file in the repo root.

| Concern | Chosen tool | Rationale |
|---|---|---|
| Orchestration | **Docker Compose** | Single-command bring-up |
| Backend language | **Python 3.11** | Best LLM/agent ecosystem |
| UI | **Streamlit** | Fastest path to a demo-able UI |
| Agent framework | **LangGraph** | State-machine agents; good trace exposure |
| LLM | **Anthropic Claude (Sonnet 4.5+)** via API | Strong reasoning, good function calling |
| Semantic layer | **Cube.dev (open source)** | Simplest deployable semantic layer |
| Context graph | **Neo4j Community Edition** | Cypher is well-supported; large LLM context |
| Policy engine | **Open Policy Agent (OPA)** | Industry-standard, Rego policies |
| Feedback loop | **OpenTelemetry → local JSON + SQLite** | Reasonable trace fidelity without S3 |
| Compliance report | **WeasyPrint or Reportlab** | PDF generation in Python |
| Tests | **pytest** | Standard |

API key environment variables expected (the user will provide via `.env`):

```
ANTHROPIC_API_KEY=...
# Optional: OPENAI_API_KEY for cross-LLM comparison testing
```

---

## 4. Repository Structure

Claude Code: please initialise the repo with exactly this structure:

```
vcl-ref-impl/
├── README.md                  ← runbook for an external reviewer
├── DECISIONS.md               ← architecture decisions log, any substitutions
├── docker-compose.yml         ← single-command stack bring-up
├── .env.example               ← env vars template
├── .gitignore
├── pyproject.toml             ← Python deps (use uv or poetry)
│
├── services/
│   ├── agent-runtime/         ← FastAPI + LangGraph
│   │   ├── Dockerfile
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── graph.py       ← LangGraph state machine
│   │   │   ├── tools/         ← agent tools (one per VCL component)
│   │   │   └── audit.py       ← trace emission
│   │   └── tests/
│   │
│   ├── semantic-layer/        ← Cube.dev config
│   │   ├── Dockerfile
│   │   └── model/
│   │       └── schema/        ← Cube data models
│   │
│   ├── context-graph/         ← Neo4j with seed data
│   │   ├── Dockerfile
│   │   └── seed/
│   │       └── load.cypher
│   │
│   ├── policy-engine/         ← OPA with policies
│   │   ├── Dockerfile
│   │   └── policies/
│   │       └── vcl.rego
│   │
│   ├── feedback-loop/         ← audit aggregator
│   │   ├── Dockerfile
│   │   └── app/
│   │       └── collector.py
│   │
│   └── ui/                    ← Streamlit app
│       ├── Dockerfile
│       └── app/
│           └── main.py
│
├── data/
│   └── synthetic/             ← generated synthetic supplier-contract data
│
└── docs/
    ├── architecture.md
    ├── demo-script.md         ← exact steps to demo to a reviewer
    └── eu-ai-act-mapping.md   ← which trace fields satisfy which Article
```

---

## 5. Component Specifications

### 5.1 Semantic Layer (Cube.dev)

**Responsibility:** translate business-language questions into governed data queries.

**Schema to model:**

- `suppliers` (id, name, region, data_residency, gdpr_consent_status, risk_tier)
- `contracts` (id, supplier_id, start_date, end_date, value_usd, contains_pii, contains_secrets)
- `contract_clauses` (id, contract_id, clause_type, text)
- `consents` (id, supplier_id, granted_at, scope, retention_until)

**Required Cube definitions:**

- A `cube` for each entity with measured and dimensional fields
- One pre-defined `view`: `supplier_risk_view` joining suppliers, contracts, and consents

**Interface:** REST GraphQL endpoint on `:4000/cubejs-api/v1`

### 5.2 Context Graph (Neo4j)

**Responsibility:** store the relationship structure between business entities, including provenance.

**Node types:**

- `Supplier`, `Contract`, `Clause`, `Person`, `Region`, `Consent`, `PolicyDecision`

**Edge types:**

- `(:Contract)-[:BELONGS_TO]->(:Supplier)`
- `(:Contract)-[:CONTAINS]->(:Clause)`
- `(:Supplier)-[:OPERATES_IN]->(:Region)`
- `(:Supplier)-[:HAS_CONSENT]->(:Consent)`
- `(:PolicyDecision)-[:APPLIED_TO]->(:Contract)`

**Required seed data:** Claude Code should generate ~30 suppliers across 6 regions, ~80 contracts, ~15 of which contain PII clauses, ~10 with expired or missing consent. Mix of EU, US, APAC residency.

**Interface:** Bolt protocol on `:7687`, plus a small REST wrapper for the agent tool to use.

### 5.3 Policy Engine (OPA)

**Responsibility:** enforce explicit, written policies on every data access and every agent decision.

**Required policies (in `vcl.rego`):**

1. **`allow_supplier_query`** — only return suppliers the user has organisational access to.
2. **`allow_pii_field_access`** — only expose PII fields if the requester has explicit purpose binding *and* the data subject has unexpired consent.
3. **`require_residency_match`** — when answering questions about EU data subjects, only data hosted in EU regions may be used.
4. **`mask_secrets_in_response`** — secrets clauses must be summarised, not quoted.
5. **`audit_required_on_decline`** — any policy decline must emit a structured audit event with reason.

**Interface:** OPA REST API on `:8181`. Agent runtime calls `POST /v1/data/vcl/<rule>` for each decision.

### 5.4 Agent Runtime (LangGraph + FastAPI)

**Responsibility:** decompose user queries, call the right tools, synthesise responses, emit traces.

**Graph structure (LangGraph state machine):**

```
[Receive query]
       │
       ▼
[Parse intent + entities]   ←─── tool: semantic_layer.parse
       │
       ▼
[Policy precheck: allow?]   ←─── tool: policy_engine.check
       │  no → [decline + audit] → END
       ▼
[Plan: which graph queries needed]
       │
       ▼
[Run graph queries]         ←─── tool: context_graph.query
       │
       ▼
[Per-row policy filter]     ←─── tool: policy_engine.filter
       │
       ▼
[Synthesise response]       ←─── LLM call with constrained context
       │
       ▼
[Emit final audit event]    ←─── tool: feedback_loop.emit
       │
       ▼
[Return response + trace_id]
```

**Required tools (each one calls a VCL component):**

- `semantic_layer.parse(natural_language_query) → structured_intent`
- `semantic_layer.query(measure, dimensions, filters) → rows`
- `context_graph.query(cypher_template, params) → graph_result`
- `policy_engine.check(action, principal, resource) → allow/deny + reasons`
- `policy_engine.filter(rows, principal) → filtered_rows + redactions`
- `feedback_loop.emit(event_type, payload) → trace_id`

**Interface:** `POST /query` accepting `{query: str}`, returning `{answer: str, trace_id: str, decisions: [...]}`.

### 5.5 Feedback Loop (OpenTelemetry + SQLite)

**Responsibility:** capture, persist, and replay every decision the system makes.

**Trace event schema:**

```json
{
  "trace_id": "uuid",
  "step_id": "uuid",
  "timestamp": "ISO-8601",
  "component": "semantic_layer|context_graph|policy_engine|agent|response",
  "action": "string",
  "principal": {"user": "...", "purpose": "..."},
  "input": {...},
  "output": {...},
  "policy_decisions": [
    {"policy": "...", "outcome": "allow|deny|mask", "reasons": [...]}
  ],
  "regulatory_mapping": {
    "eu_ai_act_articles": ["12", "13"],
    "nist_rmf_functions": ["MEASURE-2.7"]
  }
}
```

**Storage:** local SQLite database at `data/audit.sqlite`. Indexed by `trace_id`.

**Interface:** `GET /trace/{trace_id}` returns the full ordered list of events.

### 5.6 UI (Streamlit)

**Responsibility:** demo surface.

**Required screens:**

1. **Query screen.** Single text input. Pre-filled with the worked-use-case query (see §6).
2. **Response screen.** Shows the answer with explicit "[redacted: policy X]" markers where data was masked.
3. **Trace viewer.** Collapsible tree showing every event in order, each labelled with which VCL component produced it, with policy decisions inline.
4. **Compliance report export.** "Generate PDF" button → produces a regulator-addressable report mapping the trace to EU AI Act articles and NIST RMF functions.

---

## 6. Demo Workflow — The Worked Use Case

This is the *exact* scenario from Section 5 of the paper. The prototype must handle this query end-to-end:

> **"Show me the top five suppliers in EMEA with contracts expiring before December 2026, where the contracts contain PII clauses. Only include suppliers whose data subjects have valid GDPR consent."**

**Expected behaviour:**

1. UI sends query to agent runtime.
2. Agent parses → intent: `find_suppliers`, filters: `region=EMEA, contract_end<=2026-12-31, contains_pii=true, consent_status=valid`.
3. Agent calls `policy_engine.check`: is this user permitted to query supplier-PII intersections? → ALLOW with purpose binding.
4. Agent calls semantic layer to get the filter-shaped query.
5. Agent calls context graph to retrieve matching supplier-contract pairs with provenance.
6. Per-row policy filter:
   - Two rows have expired consent → masked with "[redacted: policy `allow_pii_field_access`]"
   - One row references US-residency data → excluded with audit event
7. Agent synthesises a top-five list explaining what is shown and what is redacted.
8. Final response includes a trace ID.
9. User clicks trace → sees all 7 steps with the policy decisions visible.
10. User clicks export → downloads a PDF compliance report.

**Acceptance test:** running `pytest services/agent-runtime/tests/test_worked_use_case.py` must pass and must verify all 10 steps above.

---

## 7. Implementation Plan — Phased

Each phase produces a runnable, demonstrable state. Don't move to phase N+1 until phase N runs.

### Phase 1 — Scaffold (Day 1)

- Initialise repo with the structure in §4
- Docker Compose with all six services starting (even if their handlers are stubbed)
- README with bring-up instructions
- A stub Streamlit page that says "VCL prototype — Phase 1"

### Phase 2 — Data (Day 2)

- Synthetic supplier-contract data generator (Python script in `data/synthetic/generate.py`)
- Neo4j seed loader runs on container start
- Cube.dev semantic model defined and queryable from its own UI

### Phase 3 — Policy Engine (Day 3)

- OPA service up with all five policies from §5.3
- A simple Python test client that hits each policy with allow and deny cases
- Policy unit tests in `services/policy-engine/tests/`

### Phase 4 — Agent Runtime Skeleton (Days 4–5)

- LangGraph state machine running with stubbed tools
- All tools defined with correct signatures, returning fake data
- Trace events emitted to a JSON file
- Worked-use-case query produces *some* answer end-to-end (even if incorrect)

### Phase 5 — Wire It Up (Days 6–7)

- Replace each stubbed tool with the real component call
- Verify trace events capture every decision
- Verify policy decisions actually filter results
- Acceptance test passes

### Phase 6 — UI Polish (Day 8)

- Streamlit screens for query, response, trace viewer, and compliance export
- PDF generation working
- Smoke test: ten minutes from clone to working demo

### Phase 7 — Documentation (Day 9)

- README runbook for an external reviewer
- `docs/architecture.md` with component diagrams
- `docs/demo-script.md` with the exact commands and clicks for a 10-minute walkthrough
- `docs/eu-ai-act-mapping.md` linking each trace field to its regulatory obligation

### Phase 8 — Hardening (Day 10)

- All tests passing in CI (GitHub Actions)
- One-shot demo recording (asciinema or short screen capture)
- Tag v0.1.0 release

**Total estimate:** 10 working days for one person at LLM-augmented productivity. May compress with Claude Code's parallelism.

---

## 8. Acceptance Criteria — Definition of Done

The MVP is **done** when all of the following are true:

- [ ] `docker compose up` brings up all six services successfully from a clean checkout.
- [ ] Opening `localhost:8501` shows the query interface.
- [ ] Submitting the worked-use-case query returns a correct, policy-filtered answer within 30 seconds.
- [ ] The trace viewer shows every step with policy decisions visible.
- [ ] At least two policy decisions in the trace are "deny" or "mask" — proving policy is doing real work, not theatre.
- [ ] The compliance PDF export downloads successfully and references at least EU AI Act Articles 12 and 13 and NIST RMF MEASURE-2.7.
- [ ] All tests in `pytest` pass.
- [ ] `README.md` lets a fresh reviewer go from clone to working demo in under 10 minutes.

---

## 9. Out of Scope (Explicit Non-Goals)

The following are explicitly **not** in this MVP and should not be built unless asked:

- AWS / cloud deployment (local Docker only)
- Multi-tenant isolation
- High-availability / horizontal scaling
- Real customer integrations
- A polished marketing-grade UI
- Performance benchmarking (we'll do that in the empirical study paper)
- Real LLM fine-tuning
- A REST API surface beyond the agent-runtime's `/query`
- Authentication / authorisation (assume single demo user)
- HTTPS / TLS in the demo stack

If any of these come up during the build, defer them to v0.2 and add a TODO to `DECISIONS.md`.

---

## 10. Handoff to Claude Code

This document is the complete brief. When you hand it to Claude Code, give it the following framing prompt:

> *"Build the VCL Reference Implementation as specified in `00-VCL-Prototype-Build-Spec.md`. Work through Phases 1–8 in order. After each phase, commit, push, and write a one-paragraph status update. Do not skip phases. If you need to deviate from the spec, document the decision in `DECISIONS.md` with rationale before deviating. The companion paper is at https://doi.org/10.5281/zenodo.20599942 — reference Section 5 of the paper for the worked use case and Figure 3 for the architecture diagram."*

That prompt + this spec should be sufficient for autonomous execution.

---

*End of build spec. Total prototype scope: ~10 working days. Companion paper: Zenodo DOI 10.5281/zenodo.20599942.*