# Regulatory mapping — trace fields → obligations

How the VCL trace satisfies specific EU AI Act articles and NIST AI RMF functions. The
mapping is emitted on **every** trace event (`regulatory_mapping` in the spec §5.5 schema)
and read back into the compliance PDF, making the trail *regulator-addressable*.

Source of truth: [`services/agent-runtime/app/audit.py`](../services/agent-runtime/app/audit.py)
(`REGULATORY_MAP`).

## Which trace field evidences what

| Trace field (spec §5.5) | Obligation it evidences |
|---|---|
| `trace_id`, `step_id`, `timestamp` | **EU AI Act Art. 12** (record-keeping / automatic logging): a complete, ordered, timestamped event log per decision. |
| `component`, `action`, `input`, `output` | **Art. 12** + **NIST MAP-3.4**: each step records which subsystem acted and on what — the replayable decision path. |
| `principal` (`user`, `purpose`) | **Art. 12** + **NIST GOVERN-1.2**: who asked and under what purpose binding — accountability. |
| `policy_decisions[]` (`policy`, `outcome`, `reasons`) | **Art. 9** (risk management) + **NIST MEASURE-2.7**: explicit, reasoned risk controls applied at runtime (allow/deny/mask). |
| `output.answer` with `[redacted: policy …]` markers | **Art. 13** (transparency): the user is told *what* was withheld and *which policy* withheld it. |
| `regulatory_mapping` | The index that makes all of the above addressable by obligation. |

## Per-step mapping (as emitted)

| Pipeline step (`component · action`) | EU AI Act | NIST AI RMF |
|---|---|---|
| `semantic_layer · parse_intent` / `governed_query` | Art. 12 | MAP-3.4 |
| `context_graph · query_supplier_contracts` | Art. 10 (data governance), Art. 12 | MAP-2.3 (data provenance) |
| `policy_engine · precheck_…` / `per_row_filter` | Art. 9, Art. 12 | MEASURE-2.7, GOVERN-1.2 |
| `agent · plan_queries` / `decline` / `emit_final_audit` | Art. 12, Art. 13 | MANAGE-2.2 |
| `response · synthesise_response` | Art. 12, Art. 13 | MEASURE-2.7 |

## How each policy maps to a control objective

| Policy (`vcl.rego`) | Control objective | Article |
|---|---|---|
| `allow_supplier_query` | Access control — only permitted scopes are queried | Art. 9 / Art. 12 |
| `allow_pii_field_access` | Lawful basis — PII exposed only with purpose binding **and** unexpired consent (GDPR Art. 6/7 alignment) | Art. 10 |
| `require_residency_match` | Data residency — EU-subject data stays in EU regions | Art. 10 |
| `mask_secrets_in_response` | Confidentiality — secrets summarised, never quoted | Art. 9 |
| `audit_required_on_decline` | Logging duty — every decline emits a structured, reasoned audit event | Art. 12 |

## What the worked use case demonstrates

Running the §5 query produces, in one trace: an **Art. 9** risk decision per row (the OPA
outcomes), **Art. 10** data-governance enforcement (2 masked for expired consent, 1
excluded for non-EU residency), **Art. 12** complete logging (8 persisted events), and
**Art. 13** transparency (the `[redacted: policy …]` markers in the answer). The PDF export
turns that single trace into a conformity record.

> This is a demonstration of *mechanism*, not legal advice or a certified conformity
> assessment. It shows how a verifiable context layer **produces the evidence** an
> assessment would require.
