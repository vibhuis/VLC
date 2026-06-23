# VCL Reference Implementation

A working, local, end-to-end demonstration of the **Verifiable Context Layer (VCL)**
pattern — the five-component architecture from the companion paper
*The Verifiable Context Layer* (Zenodo DOI [`10.5281/zenodo.20599942`](https://doi.org/10.5281/zenodo.20599942)).

It answers a real enterprise question with an LLM agent while **enforcing written policy
at runtime**, **tracing every decision**, and producing a **regulator-addressable audit
trail** that maps to EU AI Act Articles 9/12/13 and the NIST AI RMF.

> **The worked use case** (paper §5):
> *"Which Q3 supplier contracts have penalty-clause exposure greater than one million
> dollars, and which of those suppliers have at-risk delivery performance based on the
> last six months of operational telemetry?"*
>
> The agent resolves the penalty-exposure metric and the delivery-risk score across three
> systems of record (contract management / ERP / MES), **excludes** a supplier whose data
> is hosted outside the EU, **redacts** specific commercial terms, **masks** supplier
> contact PII, and shows you exactly why — step by step, in a tamper-evident audit trail.
>
> *(A second governance scenario — EMEA / PII / GDPR consent, from the build spec §6 —
> remains in the codebase and test suite to exercise the residency/consent/secrets
> policies, but the demo leads with the paper's §5 query.)*

---

## The five components (paper Figure 3)

| # | Component | Tool | Port | Role |
|---|-----------|------|------|------|
| 1 | Semantic layer | Cube.dev (+ DuckDB) | 4000 | business question → governed query |
| 2 | Context graph | Neo4j Community | 7474 / 7687 | entity relationships + provenance |
| 3 | Policy engine | Open Policy Agent | 8181 | enforce 5 written policies per access |
| 4 | Agent runtime | LangGraph + FastAPI + LLM | 8000 | orchestrate, reason, emit traces |
| 5 | Feedback loop | OpenTelemetry-shaped → SQLite (hash-chained) | 8200 | persist, replay & **verify** every decision |
| 5b | MCP gateway | Model Context Protocol | 9000 | exposes the VCL tools over MCP (paper §4.2) |
| — | Demo UI | Streamlit | 8501 | query · response · trace viewer · PDF export |

---

## Quick start (clone → demo in under 10 minutes)

**Prerequisites:** Docker Desktop (or any Docker engine with Compose v2).

```bash
# 1. Configure (optional — works without a key, see note below)
cp .env.example .env
#   pick a model with VCL_LLM_MODEL and paste the matching provider key

# 2. Bring up the whole stack
docker compose up --build        # first run pulls images; allow a few minutes

# 3. Open the demo
open http://localhost:8501
```

Then in the browser:

1. The query box is **pre-filled** with the worked-use-case query — click **Run**.
2. Read the policy-filtered answer (note the `[redacted: policy …]` markers).
3. Click **Show audit trace** to walk every step: semantic parse → policy precheck →
   graph query → per-row policy filter → synthesis → final audit event.
4. Click **Export compliance report (PDF)** to download the regulator-addressable report.

> **Bring your own LLM.** The agent uses [LiteLLM](https://docs.litellm.ai), so you pick
> the model with `VCL_LLM_MODEL` and supply the matching provider key — Anthropic
> (`claude-sonnet-4-6`, default), OpenAI (`gpt-4o`), Google (`gemini/…`), Groq, a local
> `ollama/…` model, etc. The LLM both *understands* the question and *writes* the answer.
> **No key at all?** The demo still runs end-to-end via a deterministic fallback; the
> governance path (semantic → graph → policy → trace) is identical either way. See
> [DECISIONS.md](DECISIONS.md) D5/D9.

---

## Verifying it works

```bash
# Unit + acceptance tests (run natively; no stack required — clients are injectable)
uv sync --extra dev
uv run pytest -q

# Policy tests against the real OPA binary
docker compose up -d policy-engine
uv run pytest services/policy-engine/tests -q
```

The acceptance test `services/agent-runtime/tests/test_worked_use_case.py` verifies all
ten steps of the worked use case from spec §6.

---

## Repository layout

```
vcl-ref-impl/
├── docker-compose.yml        single-command stack bring-up
├── DECISIONS.md              architecture decisions & deviations from the spec
├── data/synthetic/           synthetic supplier-contract data + generator
├── services/
│   ├── agent-runtime/        FastAPI + LangGraph (the agent)
│   ├── semantic-layer/       Cube.dev model
│   ├── context-graph/        Neo4j + seed loader
│   ├── policy-engine/        OPA + vcl.rego (5 policies)
│   ├── feedback-loop/        audit collector (SQLite)
│   └── ui/                   Streamlit demo
└── docs/                     architecture · demo-script · EU AI Act mapping
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — component map and the governed request flow
- [docs/demo-script.md](docs/demo-script.md) — exact 10-minute walkthrough (commands + clicks)
- [docs/eu-ai-act-mapping.md](docs/eu-ai-act-mapping.md) — which trace field satisfies which obligation
- [DECISIONS.md](DECISIONS.md) — architecture decisions and deviations from the spec

## Build phases

This repo was built in the eight phases of `00-VCL-Prototype-Build-Spec.md` §7.
Each phase is a self-contained, runnable commit. See the git history and
[DECISIONS.md](DECISIONS.md).

## License

Apache-2.0. This is a reference implementation, not a production system (see spec §1.2).
