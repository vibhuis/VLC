# Architecture

This implements **Figure 3** of *The Verifiable Context Layer* (Zenodo DOI
[`10.5281/zenodo.20599942`](https://doi.org/10.5281/zenodo.20599942)) — the five-component
VCL reference architecture — as six Docker Compose services.

## Component map

```
                              ┌──────────────────────────┐
        browser ───────────▶  │  UI · Streamlit  :8501   │
                              └────────────┬─────────────┘
                            POST /query    │   GET /trace/{id}
                                           ▼
                              ┌──────────────────────────┐
                              │ Agent runtime · :8000    │   LangGraph state machine
                              │ FastAPI + LangGraph      │   the configured LLM
                              └──┬─────┬─────┬─────┬──────┘   or deterministic fallback
            semantic_layer.*  │     │     │     │  feedback_loop.emit
                ┌─────────────┘     │     │     └──────────────┐
                ▼                   ▼     ▼                     ▼
      ┌──────────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
      │ Semantic layer   │ │ Context graph│ │ Policy engine│ │ Feedback loop    │
      │ Cube.dev +DuckDB │ │ Neo4j        │ │ OPA (Rego)   │ │ FastAPI + SQLite │
      │ :4000            │ │ :7687 /:7474 │ │ :8181        │ │ :8200            │
      └────────┬─────────┘ └──────┬───────┘ └──────────────┘ └──────────────────┘
               │ read_csv_auto    │ bolt
               ▼                  ▼
        data/synthetic/*.csv   seed/load.cypher (generated)
```

## The governed request flow (spec §5.4)

Each box is a LangGraph node; each emits a trace event to the feedback loop.

| # | Node | VCL tool | What it does |
|---|------|----------|--------------|
| 1 | `parse_intent` | `semantic_layer.parse` | NL question → structured intent (geo, end-date bound, PII flag, residency scope, limit) |
| 2 | `policy_precheck` | `policy_engine.check` | `allow_supplier_query` — gate the whole request; **deny → decline + audit → END** |
| 3 | `plan` | agent | record the query plan |
| 4 | `run_queries` | `semantic_layer.query` + `context_graph.query` | Cube aggregate over `supplier_risk_view`; Neo4j retrieval of matching supplier-contract pairs with provenance |
| 5 | `policy_filter` | `policy_engine.filter` | per-row `require_residency_match` (exclude), `allow_pii_field_access` (mask), `mask_secrets_in_response` (mask); declines emit `audit_required_on_decline` |
| 6 | `synth` | LLM | top-N answer with `[redacted: policy …]` markers |
| 7 | `final_audit` | `feedback_loop.emit` | final event; return `answer` + `trace_id` |

## Why these substitutions (see [DECISIONS.md](../DECISIONS.md))

- **Cube + embedded DuckDB** over the synthetic CSVs — a SQL semantic layer with no extra
  database container (D3).
- **Neo4j bolt driver in the agent**, not a separate REST wrapper — keeps six services (D4).
- **Deterministic synthesiser fallback** when no `ANTHROPIC_API_KEY` — the demo runs for
  everyone; the governance path is identical, only the prose differs (D5).
- **ReportLab** for the PDF — pure Python, no system libraries (D6).

## Data model

Relational (Cube) and graph (Neo4j) describe the **same** synthetic records, generated
deterministically by [`data/synthetic/generate.py`](../data/synthetic/generate.py):

- `Supplier(id, name, region, geo, data_residency, gdpr_consent_status, risk_tier)`
- `Contract(id, supplier_id, start_date, end_date, value_usd, contains_pii, contains_secrets)`
- `Clause(id, contract_id, clause_type, text)` · `Consent(id, supplier_id, granted_at, scope, retention_until)`
- Graph adds `Region`, `Person` (data subjects), and `PolicyDecision` provenance nodes with
  edges `BELONGS_TO`, `CONTAINS`, `OPERATES_IN`, `HAS_CONSENT`, `HAS_DATA_SUBJECT`, `APPLIED_TO`.

~30 suppliers / ~90 contracts / 6 regions. The scenario is seeded so the worked-use-case
query yields exactly **5 shown / 2 masked / 1 excluded** (see [demo-script.md](demo-script.md)).

## Trace & audit

Every node emits a spec §5.5 event: `{trace_id, step_id, timestamp, component, action,
principal, input, output, policy_decisions[], regulatory_mapping{eu_ai_act_articles[],
nist_rmf_functions[]}}`, persisted to `data/audit.sqlite` and replayable via
`GET /trace/{trace_id}`. The regulatory mapping is what makes the trace
regulator-addressable — see [eu-ai-act-mapping.md](eu-ai-act-mapping.md).
