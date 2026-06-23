# Demo script — 10-minute walkthrough

Exact commands and clicks to take an unaffiliated reviewer from a clean checkout to a
working, audited answer. Mirrors the success criteria in spec §1.3 and §8.

## 0. Prerequisites (30s)

- Docker Desktop (or any Docker engine + Compose v2) running.
- An `ANTHROPIC_API_KEY` is **optional** — the demo runs without one (deterministic
  synthesiser). With a key, the LLM writes the answer prose.

## 1. Bring up the stack (≈3–4 min first run, then seconds)

```bash
git clone <repo-url> && cd vcl-ref-impl
cp .env.example .env          # optionally paste ANTHROPIC_API_KEY
docker compose up --build     # first run pulls Neo4j/Cube/OPA images
```

Wait until all six services are healthy:

```bash
docker compose ps             # semantic-layer, context-graph, policy-engine,
                              # feedback-loop, agent-runtime all "healthy"; ui "up"
```

## 2. Run the worked use case in the browser (2 min)

Open <http://localhost:8501>.

1. The **query box is pre-filled** with the paper's §5 question:
   > *"Which Q3 supplier contracts have penalty-clause exposure greater than one million
   > dollars, and which of those suppliers have at-risk delivery performance based on the
   > last six months of operational telemetry?"*
2. Click **Run query**.
3. Read the **Answer**. You should see:
   - **4 suppliers shown** — at-risk delivery, Q3 penalty exposure > $1M, EU-resident —
     ranked by penalty exposure, each **resolved across ERP / MES / CMS** ids.
   - **2 of them** show `[redacted: policy redact_commercial_terms]` instead of the specific
     penalty amount (aggregate exposure still disclosed); **all** show
     `[redacted: policy mask_supplier_contact_pii]` for the contact.
   - **1 excluded** by `require_residency_match` — at-risk and high-exposure, but its
     operational data is hosted in the US, not the EU (paper §4.3).
   - **2 flagged** for exposure but delivery within tolerance (not at-risk); one more is
     below the $1M threshold and filtered out.
   - One §5 query exercises **5 of the 7 policies** — policy doing real work, not theatre.

## 3. Inspect the audit trace (2 min)

1. Toggle **Show audit trace**.
2. Walk the 8 steps — each labelled with its VCL component:
   `semantic_layer · parse_intent` → `policy_engine · precheck_allow_supplier_query` →
   `agent · plan_queries` → `semantic_layer · governed_query` →
   `context_graph · query_supplier_contracts` → `policy_engine · per_row_filter`
   (expand it: per-supplier `allow` / `mask` / `deny` decisions with reasons) →
   `response · synthesise_response` → `agent · emit_final_audit`.
3. Note each step's EU AI Act / NIST mapping in the caption.

## 4. Export the compliance report (1 min)

1. Click **Generate compliance report (PDF)**, then **⬇ Download**.
2. Open the PDF. It contains: the answer, the ordered decision path (with policy
   outcomes colour-coded), and a **Regulatory mapping** table tying steps to EU AI Act
   Art. 9/10/12/13 and NIST AI RMF functions (incl. MEASURE-2.7).

## 5. (Optional) Prove it from the command line (1 min)

```bash
python scripts/smoke.py        # 8/8 checks: exposure/redactions/residency/cross-system, integrity
uv run pytest -q               # all pass; 2 skipped (live-stack opt-in)
VCL_LIVE=1 uv run pytest services/agent-runtime/tests/test_live_stack.py -q   # vs running stack
```

> The build-spec §6 scenario (EMEA / PII / GDPR consent) is not surfaced in the UI but
> remains in the agent and test suite — it exercises the `require_residency_match`,
> `allow_pii_field_access` and `mask_secrets_in_response` policies. The §5 query above
> already exercises 5 of the 7 policies live (the §5 trace also maps to EU AI Act Art. 14,
> human oversight, paper §5.3).

## Tear down

```bash
docker compose down            # add -v to also drop the Neo4j volume + audit.sqlite
```

## Talking points (the claim this proves)

- **Governed, not bolted-on:** the two masked rows and one excluded row are produced by
  OPA at runtime, recorded with reasons — remove the policy and the answer changes.
- **Replayable:** the entire decision path is in `data/audit.sqlite`, retrievable by
  `trace_id`; an auditor could replay it.
- **Regulator-addressable:** the PDF maps each step to a specific obligation.
