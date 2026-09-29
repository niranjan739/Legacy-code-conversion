import streamlit as st
import glob
import os

st.markdown("# 📁 Codebase & Documents")
st.write("Browse the Master Architecture Documents and the newly Generated Target Code.")

tab1, tab2 = st.tabs(["Architecture Documents", "Generated Code"])

with tab1:
    docs = glob.glob("master_docs/*.md")
    if not docs:
        st.info("No Master Documents generated yet.")
    else:
        selected_doc = st.selectbox("Select Document", docs)
        with open(selected_doc, "r", encoding="utf-8") as f:
            st.markdown(f.read())

with tab2:
    code_files = glob.glob("generated_app/**/*.*", recursive=True)
    if not code_files:
        st.info("No modern code generated yet.")
    else:
        selected_code = st.selectbox("Select Source File", [f for f in code_files if os.path.isfile(f)])
        if selected_code:
            with open(selected_code, "r", encoding="utf-8") as f:
                st.code(f.read())
