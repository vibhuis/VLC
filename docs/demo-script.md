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
   > *"Show me the top five suppliers in EMEA with contracts expiring before December 2026,
   > where the contracts contain PII clauses. Only include suppliers whose data subjects
   > have valid GDPR consent."*
2. Click **Run query**.
3. Read the **Answer**. You should see:
   - **5 suppliers shown** — Helvetia Pharma AG, Nordic DataWorks AB, Britannia Logistics
     Ltd, Rhein Components GmbH, Iberia Analytics SL (ranked by contract value).
   - **2 withheld** with a red `[redacted: policy allow_pii_field_access]` marker — Baltic
     Cloud OÜ and Gallia Secure SAS (GDPR consent expired).
   - **1 excluded** — Albion Offshore Data Ltd, by `require_residency_match` (data hosted
     in the US, not the EU).
   - The metrics row shows **≥ 3 denied/masked** decisions — policy doing real work, not theatre.

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
python scripts/smoke.py        # 7/7 checks: shown/masked/excluded, trace persisted, Art 12&13
uv run pytest -q               # 37 passed, 2 skipped (live-stack opt-in)
VCL_LIVE=1 uv run pytest services/agent-runtime/tests/test_live_stack.py -q   # vs running stack
```

## 6. The paper's §5 scenario (penalty exposure + delivery risk)

In the UI, switch the **Worked use case** selector to **"Paper §5 — penalty exposure &
at-risk delivery"** (pre-fills the paper's query), then **Run query**. You should see:

- **5 at-risk suppliers** ranked by **penalty exposure** (Q3 contracts, exposure > $1M,
  *and* at-risk delivery from 6 months of telemetry).
- **2 of them** show `[redacted: policy redact_commercial_terms]` instead of the specific
  penalty amount — the aggregate exposure is still disclosed (analyst lacks contract-detail
  clearance).
- **All shown** show `[redacted: policy mask_supplier_contact_pii]` for the contact.
- Each supplier line shows **cross-system identity resolution** (ERP / MES / CMS ids
  resolved to one canonical supplier).
- **2 suppliers** flagged for exposure > $1M but **delivery within tolerance** are listed
  separately (not at-risk); one more is below the $1M threshold and filtered out.

The trace, integrity check and PDF export work identically; the §5 trace additionally maps
to **EU AI Act Art. 14** (human oversight, paper §5.3).

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
