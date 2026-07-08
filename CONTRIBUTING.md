# Contributing

Thanks for your interest. This repo is the reference implementation accompanying the paper
*The Verifiable Context Layer* (on [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6900918)). It is a
demonstrator / starting point, not a production system — see [DECISIONS.md](DECISIONS.md).

## Development setup

```bash
# Python tooling (tests, lint) — no Docker needed for the hermetic suite
uv sync --extra dev
uv run pytest -q
uv run ruff check services data scripts

# Full stack
cp .env.example .env          # optional: set a provider key + VCL_LLM_MODEL
docker compose up --build
python scripts/smoke.py       # end-to-end check against the running stack
```

OPA policy tests need the `opa` binary (or the policy-engine container):

```bash
opa test services/policy-engine/policies        # 19 unit tests
```

## Code map

| Path | What |
|---|---|
| `services/agent-runtime/app/scenarios/` | **domain logic** — one `Scenario` class per question family (the main extension point) |
| `services/agent-runtime/app/graph.py` | the LangGraph governed pipeline (domain-agnostic) |
| `services/agent-runtime/app/tools/` | toolbox: `live` (real services), `fixtures` (deterministic), `mcp` (over MCP), `base` (registry-driven orchestration) |
| `services/agent-runtime/app/audit.py` | trace events + regulatory mapping |
| `services/feedback-loop/app/collector.py` | tamper-evident hash-chained audit log (`/verify`, `/prov`) |
| `services/policy-engine/policies/` | OPA Rego policies + unit tests |
| `services/semantic-layer/model/` | Cube data model |
| `services/context-graph/seed/` | generated Neo4j seed |
| `services/ui/app/` | Streamlit demo + ReportLab PDF |
| `data/synthetic/generate.py` | deterministic data generator |

## Common changes

- **Add a domain / question type** → [docs/adapting-to-your-domain.md](docs/adapting-to-your-domain.md)
  (add a `Scenario` + a toolbox query + a Rego policy + a test).
- **Add a policy** → edit `vcl.rego`, add a `vcl_test.rego` case, mirror it in
  `FixtureToolbox._decide`, and add a `test_policy_parity` case (the parity test keeps the
  mirror honest against live OPA).
- **Regenerate data** → `python data/synthetic/generate.py` (deterministic; CI checks it
  doesn't drift). Wipe the Neo4j volume to re-seed: `docker compose down -v`.

## Conventions

- `ruff` must pass (`line-length = 100`). Keep diffs minimal and match surrounding style.
- Every policy decision must be reasoned (`reasons: [...]`) and land in the trace.
- Tests: a hermetic test (FixtureToolbox, no services) for logic; a live test (skipped if
  the stack is down) for integration. CI runs both.
- Don't break the determinism of the data generator or the worked-use-case acceptance test.

## CI

`.github/workflows/ci.yml` runs ruff, `opa test`, a data-determinism check, the pytest
suite, and a `docker compose` smoke test on every push/PR.

## License

By contributing you agree your contributions are licensed under Apache-2.0.
