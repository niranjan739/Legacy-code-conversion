import os
import glob
import config
from utils import setup_logger

logger = setup_logger("AggregatorAgent")

def run_aggregator():
    """
    Aggregates all markdown chunks in documentation/ into master_docs/.
    This uses the 'copy/paste' concatenation method directly, bypassing the LLM
    to ensure 100% data retention and save API costs.
    """
    if not os.path.exists(config.DOCUMENTATION_DIR):
        logger.error("No documentation folder found to aggregate.")
        raise FileNotFoundError("No documentation folder found to aggregate.")

    class_dirs = [d for d in os.listdir(config.DOCUMENTATION_DIR) if os.path.isdir(os.path.join(config.DOCUMENTATION_DIR, d))]
    
    aggregated_count = 0
    for c_dir in class_dirs:
        md_files = glob.glob(f"{config.DOCUMENTATION_DIR}/{c_dir}/*.md")
        
        if not md_files:
            logger.warning(f"Class directory {c_dir} has no markdown files. Skipping.")
            continue
            
        # Sort to ensure chunk_01, chunk_02, etc. are processed in order
        md_files.sort()
        
        all_content = []
        for f_path in md_files:
            with open(f_path, 'r', encoding='utf-8') as file:
                all_content.append(file.read())
                
        combined_content = "\n\n=== NEXT CHUNK ===\n\n".join(all_content)
        
        os.makedirs(config.MASTER_DOCS_DIR, exist_ok=True)
        master_path = os.path.join(config.MASTER_DOCS_DIR, f"{c_dir}_Master.md")
        
        with open(master_path, "w", encoding="utf-8") as f:
            f.write(f"# MASTER DOCUMENT: {c_dir}\n\n")
            f.write(combined_content)
        
        aggregated_count += 1
            
    summary = f"Successfully aggregated {aggregated_count} documentation classes into {config.MASTER_DOCS_DIR}/"
    logger.info(summary)
    return summary
