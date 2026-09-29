import streamlit as st
import os
import time

st.markdown("# ⏱️ Pipeline Status")
st.write("Real-time streaming logs of the backend Agentic Pipeline.")

log_file = "pipeline_run.log"

if st.button("🔄 Manual Refresh"):
    st.rerun()

log_container = st.empty()

if os.path.exists(log_file):
    with open(log_file, "r") as f:
        log_container.code(f.read())
else:
    st.info("No pipeline is currently running. Launch one from the Configuration page.")
