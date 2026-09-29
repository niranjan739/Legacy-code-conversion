import streamlit as st
import glob
import os
import time
from langchain_core.messages import HumanMessage
from agents.documentation_agent import create_doc_agent

st.markdown("# ✍️ Human-in-the-Loop Refinement")
st.write("Review flagged documents, fix AI hallucinations, and resume the pipeline.")

# Lazy initialize agent
if "doc_agent" not in st.session_state:
    st.session_state.doc_agent = None

flagged_files = glob.glob("flagged_documents/**/*.md", recursive=True)

if not flagged_files:
    st.success("🎉 Pipeline is clean. No documents are flagged for review.")
    
    st.markdown("### Final Sign-off")
    st.write("If the pipeline is paused before Code Generation, you can approve the system architecture here.")
    if st.button("🚀 Approve Architecture & Resume Code Generation", use_container_width=True):
        st.success("Approval logged. Pipeline will resume in the background.")
        # In a real deployed version, this would update the LangGraph state.
else:
    selected_file = st.selectbox("Select a file to review:", flagged_files)
    st.write(f"**Reviewing File:** `{selected_file}`")
    
    with open(selected_file, 'r', encoding='utf-8') as f:
        content = f.read()
        
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("#### Document Content")
        st.markdown(content)
        
    with col2:
        st.markdown("#### Human Action")
        user_comments = st.text_area("Add your comments for the rewrite:", height=150)
        target_path = selected_file.replace("flagged_documents", "documentation").replace("\\", "/")
        
        if st.button("✅ Approve (No Rewrite)", use_container_width=True):
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            os.rename(selected_file, target_path)
            st.success(f"Moved to {target_path}. Refreshing...")
            time.sleep(1)
            st.rerun()
            
        if st.button("🔄 Send for Rework", use_container_width=True):
            if not user_comments.strip():
                st.error("Please add comments before sending for rework.")
            else:
                if st.session_state.doc_agent is None:
                    st.session_state.doc_agent = create_doc_agent()
                    
                with st.spinner("Agent is rewriting the documentation..."):
                    rework_instruction = f"""
This documentation was flagged by the QA Evaluator and a Human Reviewer.
Please rewrite the documentation for this chunk based on the human's feedback.

Original File Content:
```markdown
{content}
```

Human Feedback:
{user_comments}

Rewrite the documentation and write it to '{target_path}'. Ensure you follow all metadata rules.
"""
                    inputs = {"messages": [HumanMessage(content=rework_instruction)]}
                    
                    try:
                        for chunk in st.session_state.doc_agent.stream(inputs, stream_mode="values"):
                            pass 
                            
                        if os.path.exists(selected_file):
                            os.remove(selected_file)
                        st.success(f"Rewrite complete! Saved to {target_path}. Refreshing...")
                        time.sleep(2)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error during rework: {e}")
