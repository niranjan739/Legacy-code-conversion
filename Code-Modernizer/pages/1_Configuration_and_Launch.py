import streamlit as st
import subprocess
import sys
import os

st.markdown("# 🚀 Configuration & Launch")
st.write("Launch the autonomous Supervisor to orchestrate the pipeline.")

with st.expander("⚙️ Pipeline Configuration", expanded=True):
    col_s, col_t = st.columns(2)
    with col_s:
        source_lang = st.selectbox("Source Language", ["java", "cobol", "python"], index=0)
    with col_t:
        target_framework = st.selectbox("Target Framework", ["java_springboot", "python_fastapi", "javascript_express"], index=0)

import glob
st.markdown("### 📊 Complexity Analysis")
if st.button("Analyze Input Codebase"):
    ext = ".java" if source_lang == "java" else ".cbl" if source_lang == "cobol" else ".py"
    files = glob.glob(f"legacy_source/**/*{ext}", recursive=True)
    if not files:
        st.warning(f"No {ext} files found in legacy_source/")
    else:
        total_loc = 0
        for f in files:
            with open(f, 'r', encoding='utf-8', errors='ignore') as file:
                total_loc += len(file.readlines())
                
        estimated_chunks = max(1, total_loc // 200) # Rough estimate
        estimated_cost = estimated_chunks * 0.05 # Assume $0.05 per chunk across all agents
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Files Detected", len(files))
        c2.metric("Total Lines of Code", f"{total_loc:,}")
        c3.metric("Estimated Chunks", estimated_chunks)
        c4.metric("Estimated LLM Cost", f"${estimated_cost:.2f}")

st.markdown("---")        
if st.button("▶ Launch Agentic Pipeline", use_container_width=True):
    with st.spinner("Pipeline is running in the background... Please go to the 'Pipeline Status' page to monitor logs."):
        try:
            log_file = "pipeline_run.log"
            with open(log_file, "w") as f:
                f.write("Pipeline starting...\n")
                
            process = subprocess.Popen(
                [sys.executable, "agentic_main.py", "--source-lang", source_lang, "--target-framework", target_framework], 
                stdout=open(log_file, "a"),
                stderr=subprocess.STDOUT,
                text=True
            )
            st.success("✅ Pipeline successfully launched! Open the 'Pipeline Status' page from the sidebar.")
        except Exception as e:
            st.error(f"Failed to launch pipeline: {e}")
