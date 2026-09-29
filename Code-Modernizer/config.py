import os
from langchain_openai import AzureChatOpenAI

# Directory Configuration
LEGACY_SOURCE_DIR = "legacy_source"
DOCUMENTATION_DIR = "documentation"
FLAGGED_DIR = "flagged_documents"
MASTER_DOCS_DIR = "master_docs"
MODERNIZED_SOURCE_DIR = "modernized_source"
CHROMA_DB_DIR = "./chroma_db"
SQLITE_DB_PATH = "state_checkpoint.db"
AUDIT_REPORT_PATH = "audit_report.json"

def get_llm(temperature=0, response_format=None):
    """
    Factory function to initialize the LLM consistently across all agents.
    """
    kwargs = {
        "api_key": os.environ.get("AZURE_OPENAI_KEY_GPT4o"),
        "azure_endpoint": os.environ.get("AZURE_OPENAI_ENDPOINT"),
        "azure_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
        "api_version": "2025-01-01-preview",
        "temperature": temperature,
        "max_retries": 6
    }
    
    if response_format:
        kwargs["model_kwargs"] = {"response_format": response_format}
        
    return AzureChatOpenAI(**kwargs)
