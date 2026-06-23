# Roadmap

Status: **v0.2 reference implementation.** It demonstrates the five-component VCL pattern
end-to-end with a tamper-evident audit trail, an MCP runtime, and the paper's §5 worked use
case. It is intentionally *not* production software (see [DECISIONS.md](../DECISIONS.md) §9).

This roadmap lists what would move it from "credible demonstrator" toward "adoptable
foundation". Contributions welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).

## Done (v0.1 → v0.2)
- Five components wired end-to-end (Cube, Neo4j, OPA, LangGraph, feedback loop) + Streamlit UI.
- Provider-agnostic LLM via LiteLLM (model-agnosticism, paper §6.3).
- **Tamper-evident, PROV-shaped audit log** — hash-chained, `/verify`, `/prov` (paper §6.1).
- **MCP gateway** — the agent/tool runtime implements MCP (paper §4.2).
- Paper §5 worked use case (penalty exposure + at-risk delivery, cross-system identity
  resolution, data-residency exclusion) exercising 5 of 7 policies live.
- Scenario-plugin architecture + [adapting guide](adapting-to-your-domain.md).
- Apache-2.0, CI, deterministic data, regulator-addressable PDF.

## Next (candidate v0.3)
**Adoptability**
- [ ] Real data connectors — promote the opt-in Postgres profile to first-class; add a
      second source (e.g. a SQL warehouse) so it's not synthetic-only.
- [ ] Pull domain config (schema, policies, parser hints, synthesis templates) into a
      clearly-marked `domain/` layer so swapping domains touches one place.
- [ ] A `cookiecutter`-style "new domain" scaffold.

**Verification depth (paper §8 primitives)**
- [ ] Real OpenTelemetry export (OTLP) + an optional collector/Jaeger profile.
- [ ] Continuous-assurance signals (semantic-resolution / outcome / drift, paper §5.2;
      AAGATE-style) emitted from the feedback loop.
- [ ] OPA signed bundles + decision logs (independently verifiable policy artifacts).
- [ ] SHACL / type grounding contracts at the semantic layer (VeriGuard-style, paper Table 3).
- [ ] Runtime-enforcement hooks (AgentSpec / AgentGuard) over the trace.
- [ ] Externalised audit-log integrity (publish chain heads to a transparency log /
      append-only store) and per-event signing.

**Production concerns (explicitly out of scope today, paper §9 / spec §9)**
- [ ] AuthN/AuthZ and multi-tenant isolation (replace the single demo principal).
- [ ] HA / horizontal scaling; secrets management; HTTPS/TLS in the stack.
- [ ] Performance & cost benchmarking (the empirical-study paper, paper §10.2).

## Non-goals
- Becoming a vendor product or competing with the EIL implementations in the paper §7.
  The VCL is a *pattern*; this repo proves it composes — adopters bring their own stack.
