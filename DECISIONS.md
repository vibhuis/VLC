# Architecture Decisions Log

This file records every deviation from `00-VCL-Prototype-Build-Spec.md` together with
its rationale, per the handoff instruction in spec §10. Each entry is dated and
references the relevant spec section.

> The build spec (§10) states it is "the complete brief" and reproduces the worked
> use case (paper §5) in spec §6 and the reference architecture (paper Figure 3) in
> spec §2. Those reproductions are treated as authoritative; the companion paper
> (Zenodo DOI `10.5281/zenodo.20599942`) is cited in the docs.

---

## D1 — Build verified against Docker Desktop on the build host
**Spec ref:** §1.3, §8 · **Date:** 2026-06-18

Docker Desktop (engine 28.0.1, Compose v2.33, Linux engine, 8 GB) is available on the
build host, so the full six-service stack is brought up with `docker compose up` and the
end-to-end worked-use-case flow is exercised during the build — not just the parts that
run without Docker. The `pytest` suite additionally runs natively (with the LLM and
service clients injectable) so tests pass with or without the stack running.

## D2 — Spec file committed under the name the brief references
**Spec ref:** §10 · **Date:** 2026-06-18

The brief refers to `00-VCL-Prototype-Build-Spec.md`. The source file on disk was
named `# VCL Reference Implementation — Build S.md`. It is copied verbatim into the
repo root under the referenced name so the repo is self-contained.

## D3 — Cube.dev reads synthetic data via embedded DuckDB (no separate RDBMS service)
**Spec ref:** §5.1, §2 (six services) · **Date:** 2026-06-18

Cube.dev is a SQL semantic layer and needs a SQL data source, but the spec's
architecture diagram has exactly six services with no relational database. Rather than
add a seventh (Postgres) container, Cube uses its **DuckDB** driver to read the
synthetic CSVs (`data/synthetic/*.csv`) directly via `read_csv_auto`. This keeps the
stack at six services and needs no DB server. The same synthetic records are loaded
into Neo4j as the context graph, so both layers describe identical data.

## D4 — Context-graph REST wrapper folded into the agent's bolt client
**Spec ref:** §5.2 ("plus a small REST wrapper for the agent tool to use") · **Date:** 2026-06-18

The spec offers a REST wrapper around Neo4j as optional ("plus a small…"). The agent's
`context_graph.query` tool uses the official Neo4j Python **bolt driver** directly,
which is simpler and removes a network hop. The context-graph service therefore stays a
single Neo4j container (custom image that self-seeds on start), keeping the six-service
count.

## D5 — Deterministic fallback synthesiser when `ANTHROPIC_API_KEY` is absent
**Spec ref:** §3 (Claude as LLM), §1.3 (clone-and-run) · **Date:** 2026-06-18

Claude (`claude-sonnet-4-6`) is the LLM backbone when `ANTHROPIC_API_KEY` is set. To
keep the open-source demo and the test suite runnable by a reviewer **without** an API
key, the response-synthesis node falls back to a deterministic, template-based
synthesiser that produces the same structured answer from the policy-filtered rows. The
governance path (semantic → graph → policy → trace) is identical in both modes; only
the natural-language phrasing of the final answer differs. This makes success
criterion §1.3 ("clone, run, see an answer") hold for everyone.

## D6 — PDF compliance report uses ReportLab
**Spec ref:** §3 ("WeasyPrint or Reportlab") · **Date:** 2026-06-18

The spec permits either. ReportLab is chosen because it is pure-Python and needs no
system libraries (WeasyPrint requires cairo/pango/gdk-pixbuf), keeping the UI
Dockerfile slim and the build reproducible.

## D7 — Per-service `requirements.txt` plus a root `pyproject.toml`
**Spec ref:** §4 (`pyproject.toml`) · **Date:** 2026-06-18

Each containerised Python service pins its own `requirements.txt` for a minimal image.
The root `pyproject.toml` defines the dev/test environment (pytest, ruff, the
agent-runtime package) used for local `uv run pytest`. Both are kept in sync.

## D8 — feedback-loop service listens on :8200
**Spec ref:** §5.5 (port unspecified) · **Date:** 2026-06-18

The spec gives the feedback loop an interface (`GET /trace/{trace_id}`) but no port.
Port **8200** is assigned (avoids the other services' ports) and recorded in
`.env.example` and `docker-compose.yml`.

---

## Deferred to v0.2 (out-of-scope per spec §9)

- AWS/cloud deployment, multi-tenancy, HA/scaling, real integrations.
- Authentication/authorisation (single demo user assumed).
- HTTPS/TLS in the demo stack.
- Performance benchmarking (empirical-study paper).
- OpenTelemetry OTLP export to a collector — the feedback loop persists OTel-shaped
  spans to SQLite directly (spec §3 says "OpenTelemetry → local JSON + SQLite"); wiring
  a full OTLP collector is deferred.
