import os
import glob
from langchain_core.messages import HumanMessage, SystemMessage
import config
from utils import setup_logger

logger = setup_logger("ArchitectureAgent")

def run_architecture_generation(state):
    logger.info("\n[ArchitectureAgent] Generating System-Level Architecture...")
    
    llm = config.get_llm()
    master_files = glob.glob(f"{config.MASTER_DOCS_DIR}/*.md")
    
    if not master_files:
        return "No Master Documents found to build architecture from."
        
    all_docs = ""
    for fpath in master_files:
        if "system_architecture.md" in fpath:
            continue
        with open(fpath, "r", encoding="utf-8") as f:
            all_docs += f"\n--- {os.path.basename(fpath)} ---\n{f.read()}\n"
            
    system_prompt = """
    You are a Principal Enterprise Architect.
    You will be given the complete chunk-level documentation of a legacy application.
    Your task is to analyze all the components and produce a unified System Architecture Document.
    
    CRITICAL REQUIREMENT - CROSS-CHUNK CONSISTENCY CHECK:
    You must verify that cross-references between chunks are consistent. Does Chunk A's reference to Method X match Chunk B's definition of Method X?
    
    Your output MUST include:
    1. Executive Summary
    2. High-Level Architecture (Core components and their responsibilities)
    3. Data Flow & Integration Points
    4. Cross-Component Consistency Rules
    5. Consistency Audit: Explicitly list any inconsistencies found between the chunks (or state "No inconsistencies found").
    
    Output ONLY Markdown.
    """
    
    try:
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=all_docs)
        ])
        
        output_path = os.path.join(config.MASTER_DOCS_DIR, "system_architecture.md")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(response.content)
            
        logger.info(f"[ArchitectureAgent] Successfully generated system_architecture.md")
        return f"System Architecture generated successfully at {output_path}."
        
    except Exception as e:
        logger.error(f"Failed to generate architecture: {e}")
        return f"Failed to generate architecture: {e}"
