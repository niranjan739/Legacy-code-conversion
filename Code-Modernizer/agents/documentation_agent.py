import os
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma
import config
from utils import setup_logger, sanitize_path

logger = setup_logger("DocAgent")

# Hoist embeddings and Chroma to module-level for performance
embeddings = FastEmbedEmbeddings()
vector_store = Chroma(persist_directory=config.CHROMA_DB_DIR, embedding_function=embeddings)

@tool
def read_java_file(file_path: str) -> str:
    """Reads and returns the contents of a Java file given its file path."""
    logger.info(f"Reading code from: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return f"Error reading file: {e}"

@tool
def write_documentation(file_path: str, content: str) -> str:
    """Writes the provided markdown documentation content to the specified file path."""
    logger.info(f"Writing documentation to: {file_path}")
    try:
        # Sanitize path to prevent path traversal
        safe_path = sanitize_path(os.getcwd(), file_path)
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote documentation to {safe_path}"
    except Exception as e:
        logger.error(f"Error writing to file {file_path}: {e}")
        return f"Error writing to file: {e}"

@tool
def search_codebase(query: str) -> str:
    """Searches the vector database for code chunks matching the query to provide context."""
    logger.info(f"Searching codebase for: {query}")
    try:
        results = vector_store.similarity_search(query, k=3)
        
        if not results:
            return "No matching code found in the database."
            
        context = "\n\n---\n\n".join([f"Source: {res.metadata.get('source', 'Unknown')}\n{res.page_content}" for res in results])
        return context
    except Exception as e:
        logger.error(f"Error searching codebase: {e}")
        return f"Error searching codebase: {e}"

def create_doc_agent():
    # Initialize the LLM (gpt-4o) using Azure
    llm = config.get_llm()
    
    tools = [read_java_file, write_documentation, search_codebase]
    
    system_prompt = """
    You are an autonomous expert technical writer and Java developer. 
    Your task is to read a chunk of a legacy Java codebase, generate well-structured and easy-to-read Markdown documentation for it, and save the documentation.
    
    IMPORTANT METADATA REQUIREMENT:
    Every Markdown file you generate MUST begin with a YAML frontmatter block containing metadata. For example:
    ---
    original_file: "path/to/file.java"
    language: "Java"
    chunk_id: "<generate_a_unique_id>"
    confidence_score: <score_between_0.0_and_1.0>
    external_dependencies: [<list_of_external_classes>]
    ---
    
    Below the metadata, document the specific chunk of code provided. You MUST explicitly extract and document the following into distinct sections:
    1. **Business Rules**: Any core business logic (e.g., pricing, eligibility, decisions).
    2. **Validation Logic**: Any input checks, constraints, or assertions.
    3. **Integration Points**: Any external API calls, database queries, or dependencies.
    4. **Technical Implementation**: Explain its general purpose and methods.
    
    You have tools to read files, write files, and search the codebase.
    If you encounter unknown methods or classes in the chunk you are reading, use the search_codebase tool to find their definitions before writing the documentation.
    """
    
    return create_react_agent(llm, tools, prompt=system_prompt)
