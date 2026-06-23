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

## D5 — Deterministic fallback when no LLM provider key is configured
**Spec ref:** §3 (Claude as LLM), §1.3 (clone-and-run) · **Date:** 2026-06-18

An LLM (default `claude-sonnet-4-6`) drives both *understanding* (question → governed
intent) and *synthesis* (final answer) when a provider key is set. To keep the
open-source demo and the test suite runnable **without** any key, both fall back to
deterministic logic (regex intent parser + template synthesiser) that produces the same
governed result. The governance path (semantic → graph → policy → trace) is identical in
every mode; only the natural-language understanding/phrasing differs. This makes success
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

## D9 — Provider-agnostic LLM via LiteLLM (user chooses the model)
**Spec ref:** §3 (Claude as LLM; "optional OPENAI_API_KEY for cross-LLM comparison") · **Date:** 2026-06-18

Rather than bind directly to one vendor SDK, the agent calls the LLM through **LiteLLM**,
a unified gateway. The model is selected with `VCL_LLM_MODEL` and the user supplies the
matching provider key (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`GROQ_API_KEY`, … or a local `ollama/` model with no key). The default remains
`claude-sonnet-4-6` (spec §3). This honours the spec's cross-LLM intent and lets a
public-repo user run the demo on whatever model they have access to. The deterministic
fallback (D5) still applies when no key is set.

## D10 — Tamper-evident, PROV-shaped audit log (verifiability)
**Paper ref:** §6.1 (verifiability is the load-bearing property), §4.2 + Table 3
(context-graph & feedback-loop primitives: MAIF cryptographic provenance [39],
PROV-AGENT [40], AAGATE [42]) · **Date:** 2026-06-21

The feedback loop now hash-chains every trace event: `entry_hash = HMAC-SHA256(key,
prev_hash ++ payload)`, stored per event. `GET /verify/{trace_id}` re-derives the chain and
reports whether it is intact (and the first broken step if not); `GET /prov/{trace_id}`
exports the trace as a W3C PROV / PROV-AGENT-shaped document carrying the chain hashes. The
UI shows an integrity badge and the PDF records the integrity verdict + chain head. This
turns the audit trail from "we logged it" into "we can prove it was not altered" — the
paper's verifiability claim, in a laptop-runnable form (no external transparency-log
service required for the demo; the server holds the HMAC key via `VCL_AUDIT_HMAC_KEY`).

## D11 — MCP at the agent/tool runtime
**Paper ref:** §2.4, §4.2, §5.2, Table 3 (the runtime "implements MCP [34]") · **Date:** 2026-06-22

The paper specifies the agent/tool runtime as the MCP surface through which agentic
workloads consume context and invoke enterprise actions. A new **mcp-gateway** service
(reusing the agent-runtime image, port 9000, Streamable HTTP at `/mcp`) exposes the VCL
tools — `semantic_query`, `context_graph_query`, `policy_check`, `policy_filter`,
`feedback_emit` — as MCP tools backed by the same governed components. The agent consumes
them through an `MCPToolbox` when `VCL_USE_MCP=1`; any external MCP client (MCP Inspector, a
copilot) can do the same. The default demo path stays in-process (`VCL_USE_MCP=0`) for
speed and zero extra moving parts, but the MCP surface is always running and the
`test_mcp_live` suite proves the full worked use case runs end-to-end over MCP. The build
spec's six-service diagram is kept; the gateway is an additive 5b sharing the agent image.

## D12 — The paper's §5 is THE worked use case; §6 retained as a tested governance scenario
**Paper ref:** §5 (worked use case), §4.2/§4.3 (governance library) · **Build-spec ref:** §6 · **Date:** 2026-06-23

The companion paper has exactly one worked use case (§5): *Q3 contracts with penalty-clause
exposure > $1M, and which of those suppliers have at-risk delivery from 6 months of
operational telemetry.* The build spec's §6 (EMEA / PII / GDPR consent) was a different,
simpler example chosen by the brief. Since the repo publishes next to the paper, the demo
leads with **§5 as the single worked use case**; §6 remains a fully-functional, unit-tested
governance scenario (not surfaced in the UI) so the residency/consent/secrets policies it
exercises stay validated.

A single query cannot fire every policy, so §5 is **enriched** to exercise as much of the
governance library as fits its narrative — it now demonstrates 5 of the 7 policies live:
`allow_supplier_query` (precheck), `require_residency_match` (one at-risk, high-exposure
supplier whose operational data is hosted in the US is **excluded** — data residency,
paper §4.3), `redact_commercial_terms`, `mask_supplier_contact_pii`, and
`audit_required_on_decline`. The remaining two (`allow_pii_field_access` GDPR-consent
expiry, `mask_secrets_in_response` secret clauses) don't fit the §5 penalty/delivery
narrative; they're validated by the OPA unit tests, the policy-parity tests, and the §6
scenario test.

Implementation: the generator adds penalty clauses, 6-month telemetry → DeliveryRiskScore,
cross-system ids (ERP/MES/CMS) resolved to canonical Supplier nodes via
`SystemRef -[:RESOLVES_TO]->`, and supplier contacts — layered on §6 data with a separate
RNG so §6 anchors/counts are unchanged. The agent is scenario-aware (`parse` tags
`penalty_delivery` vs `supplier_pii`; graph query / policy filter / synthesis branch). The
§5 trace adds EU AI Act Art. 14 (human oversight, §5.3).

**§5 result:** 4 at-risk, EU-resident, high-exposure suppliers shown (2 with commercial
terms redacted, all with contact PII masked, each resolved across ERP/MES/CMS); 1 excluded
by data residency; 2 flagged exposure-but-within-tolerance; 1 below the $1M threshold.

Simplifications (laptop-runnable): telemetry is synthetic monthly summary rows, not a live
stream; DeliveryRiskScore is precomputed; the three systems of record are represented by id
schemes + resolution nodes rather than three live source databases.

---

## Deferred to v0.2 (out-of-scope per spec §9)

- AWS/cloud deployment, multi-tenancy, HA/scaling, real integrations.
- Authentication/authorisation (single demo user assumed).
- HTTPS/TLS in the demo stack.
- Performance benchmarking (empirical-study paper).
- OpenTelemetry OTLP export to a collector — the feedback loop persists OTel-shaped
  spans to SQLite directly (spec §3 says "OpenTelemetry → local JSON + SQLite"); wiring
  a full OTLP collector is deferred.
