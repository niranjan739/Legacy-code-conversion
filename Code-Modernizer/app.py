import streamlit as st

st.set_page_config(page_title="Agentic Modernization", layout="wide", page_icon="⚡")

def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == "admin":
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password", type="password", on_change=password_entered, key="password")
        st.error("😕 Password incorrect")
        return False
    else:
        return True

if check_password():
    st.title("⚡ Agentic Modernization Dashboard")
    st.markdown("Welcome to the Enterprise Legacy Code Modernization System.")
    st.markdown("👈 Please select a page from the sidebar to begin.")
    
    st.markdown("""
    ### Pipeline Capabilities
    - **Multi-Language Support**: Convert Java, COBOL, or VB into Spring Boot, FastAPI, or Express.
    - **Semantic Analysis**: AST-based code chunking ensures logical boundaries are preserved.
    - **QA Evaluation**: Granular scoring on documentation accuracy and completeness.
    - **System Architecture**: Automatically generates a high-level cross-component system diagram.
    - **Code Generation & Healing**: Generates target code, writes unit tests, and self-heals syntax errors using local build tools.
    """)
