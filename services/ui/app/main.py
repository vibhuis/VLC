"""VCL demo UI (Streamlit). [spec §5.6]

Phase 1: a stub page proving the service is up. The query/response/trace/export
screens land in Phase 6.
"""
import streamlit as st

st.set_page_config(page_title="VCL Reference Implementation", page_icon="🔍", layout="wide")

st.title("VCL prototype — Phase 1")
st.caption("Verifiable Context Layer · reference implementation")
st.info(
    "Scaffold is up. The query interface, audit-trace viewer and compliance-report "
    "export arrive in Phase 6. See the README for the build phases."
)
