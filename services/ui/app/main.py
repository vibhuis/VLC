"""VCL demo UI (Streamlit). [spec §5.6]

Screens: query · response (with [redacted] markers) · audit-trace viewer ·
compliance-report PDF export.
"""
from __future__ import annotations

import os
import re

import httpx
import streamlit as st

from report import build_report

AGENT_URL = os.environ.get("VCL_AGENT_URL", "http://localhost:8000")
FEEDBACK_URL = os.environ.get("VCL_FEEDBACK_URL", "http://localhost:8200")

PAPER_QUERY = (
    "Which Q3 supplier contracts have penalty-clause exposure greater than one million "
    "dollars, and which of those suppliers have at-risk delivery performance based on the "
    "last six months of operational telemetry?"
)

COMPONENT_BADGE = {
    "semantic_layer": "🟦 semantic layer", "context_graph": "🟩 context graph",
    "policy_engine": "🟧 policy engine", "agent": "🟪 agent", "response": "🟨 response",
}
OUTCOME_EMOJI = {"allow": "✅ allow", "deny": "⛔ deny", "mask": "🟠 mask"}

st.set_page_config(page_title="VCL Reference Implementation", page_icon="🔍", layout="wide")
st.title("🔍 Verifiable Context Layer — demo")
st.caption("Governed enterprise AI with a regulator-addressable audit trail · "
           "companion paper Zenodo DOI 10.5281/zenodo.20599942")


def _highlight(answer: str) -> str:
    # Render [redacted: policy X] markers in red so masking is visible.
    return re.sub(r"\[redacted: policy [^\]]+\]",
                  lambda m: f":red[**{m.group(0)}**]", answer)


# --------------------------------------------------------------- query screen
st.caption("Worked use case — paper §5: penalty-clause exposure & at-risk delivery.")
with st.form("query_form"):
    query = st.text_area("Enterprise question", value=PAPER_QUERY, height=120)
    submitted = st.form_submit_button("Run query", type="primary")

if submitted:
    with st.spinner("Running governed pipeline (semantic → graph → policy → synthesis)…"):
        try:
            r = httpx.post(f"{AGENT_URL}/query", json={"query": query}, timeout=60.0)
            r.raise_for_status()
            st.session_state["result"] = r.json()
            st.session_state["query"] = query
        except httpx.HTTPError as e:
            st.error(f"Agent runtime unavailable: {e}")

result = st.session_state.get("result")

# --------------------------------------------------------------- response screen
if result:
    st.subheader("Answer")
    st.markdown(_highlight(result["answer"]))
    cols = st.columns(3)
    cols[0].metric("Trace ID", result["trace_id"][:8] + "…")
    decisions = result.get("decisions", [])
    enforced = sum(1 for d in decisions if d.get("outcome") in ("deny", "mask"))
    cols[1].metric("Policy decisions", len(decisions))
    cols[2].metric("Denied / masked", enforced)
    st.caption(f"LLM mode: {result.get('llm_mode', 'n/a')} "
               "(deterministic fallback when no ANTHROPIC_API_KEY)")

    # --------------------------------------------------------- trace viewer
    st.divider()
    if st.toggle("Show audit trace", value=False):
        events = []
        try:
            tr = httpx.get(f"{FEEDBACK_URL}/trace/{result['trace_id']}", timeout=15.0)
            tr.raise_for_status()
            body = tr.json()
            events = body["events"]
            integ = body.get("integrity", {})
            head = body.get("head_hash", "")
            if integ.get("valid"):
                st.success(f"🔒 Audit integrity verified — tamper-evident hash chain intact "
                           f"({integ.get('steps')} links). Head: `{head[:16]}…`")
            else:
                st.error(f"⚠️ Audit integrity FAILED — chain broken at step "
                         f"{integ.get('broken_at_step')}. The trace was altered.")
        except httpx.HTTPError as e:
            st.error(f"Could not load trace: {e}")

        st.write(f"**{len(events)} steps** — every decision the system made, in order:")
        for i, e in enumerate(events, 1):
            badge = COMPONENT_BADGE.get(e["component"], e["component"])
            with st.expander(f"Step {i} — {badge} · `{e['action']}`"):
                pol = e.get("policy_decisions", [])
                if pol:
                    st.markdown("**Policy decisions**")
                    for d in pol:
                        if "outcome" in d:
                            label = OUTCOME_EMOJI.get(d["outcome"], d["outcome"])
                            sid = f" · {d['supplier_id']}" if d.get("supplier_id") else ""
                            st.markdown(f"- `{d.get('policy', '?')}` → {label}{sid} "
                                        f"— {'; '.join(d.get('reasons', []))}")
                        elif "audit_required" in d:
                            st.markdown(f"- `{d.get('policy', '?')}` → audit_required="
                                        f"{d['audit_required']}")
                rm = e["regulatory_mapping"]
                st.caption("EU AI Act: " + (", ".join(f"Art. {a}" for a in rm["eu_ai_act_articles"]) or "—")
                           + "  ·  NIST RMF: " + (", ".join(rm["nist_rmf_functions"]) or "—"))
                with st.popover("input / output"):
                    st.json({"input": e["input"], "output": e["output"]})

    # --------------------------------------------------------- compliance export
    st.divider()
    st.subheader("Compliance report")
    st.write("Export a regulator-addressable PDF mapping this trace to EU AI Act Articles "
             "and NIST AI RMF functions.")
    if st.button("Generate compliance report (PDF)"):
        try:
            tr = httpx.get(f"{FEEDBACK_URL}/trace/{result['trace_id']}", timeout=15.0)
            tr.raise_for_status()
            body = tr.json()
            events = body["events"]
            principal = events[0]["principal"] if events else {}
            pdf = build_report(result["trace_id"], result["answer"], events, principal,
                               integrity=body.get("integrity"), head_hash=body.get("head_hash", ""))
            st.download_button("⬇ Download compliance_report.pdf", data=pdf,
                               file_name=f"vcl_compliance_{result['trace_id'][:8]}.pdf",
                               mime="application/pdf")
            st.success("Report generated.")
        except Exception as e:  # noqa: BLE001 — surface any failure in the demo UI
            st.error(f"Report generation failed: {e}")
else:
    st.info("Enter a question and click **Run query**. The box is pre-filled with the "
            "worked use case from the paper (§5).")
