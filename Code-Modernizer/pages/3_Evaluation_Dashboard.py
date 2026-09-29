import streamlit as st
import json
import os

st.markdown("# 📊 Evaluation Dashboard")
st.write("Granular Quality Assurance Metrics for Generated Documentation.")

if os.path.exists("audit_report.json"):
    with open("audit_report.json", "r", encoding="utf-8") as f:
        try:
            audit_data = json.load(f)
            
            total = len(audit_data)
            passed = sum(1 for d in audit_data if d.get("status", d.get("passed")) == True or d.get("status") == "passed")
            flagged = total - passed
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total Evaluated", total)
            col2.metric("Passed QA", passed)
            col3.metric("Requires Human Review", flagged)
            
            st.markdown("---")
            
            for item in audit_data:
                is_pass = item.get("status", item.get("passed")) == True or item.get("status") == "passed"
                status_emoji = "✅" if is_pass else "❌"
                
                with st.expander(f"{status_emoji} {item.get('source_file')} - {item.get('chunk_id')}"):
                    feedback = item.get("feedback", {})
                    if isinstance(feedback, str):
                        try:
                            clean_fb = feedback.strip()
                            if clean_fb.startswith("```json"): clean_fb = clean_fb[7:]
                            if clean_fb.endswith("```"): clean_fb = clean_fb[:-3]
                            fb_json = json.loads(clean_fb.strip())
                        except:
                            fb_json = {"feedback_text": feedback}
                    else:
                        fb_json = feedback
                        
                    if "completeness_score" in fb_json:
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Completeness", f"{fb_json.get('completeness_score')}/10")
                        c2.metric("Accuracy", f"{fb_json.get('accuracy_score')}/10")
                        c3.metric("Dependency", f"{fb_json.get('dependency_score')}/10")
                        c4.metric("Confidence", f"{fb_json.get('confidence')}%")
                        
                        st.markdown("**Areas for Review:**")
                        st.write(fb_json.get("areas_for_review", []))
                    
                    st.markdown("**Detailed Feedback:**")
                    st.write(fb_json.get("feedback", fb_json.get("feedback_text", "No detailed feedback.")))
                    
        except json.JSONDecodeError:
            st.error("Failed to parse audit_report.json.")
else:
    st.info("No audit report found. Run the pipeline first.")
