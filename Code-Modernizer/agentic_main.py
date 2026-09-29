import os
import sys
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from agents.orchestrator_agent import create_orchestrator_agent
import config
from utils import setup_logger

logger = setup_logger("AgenticMain")

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    if not os.environ.get("AZURE_OPENAI_KEY_GPT4o"):
        logger.error("Warning: AZURE_OPENAI_KEY_GPT4o environment variable is not set.")
        logger.error("Please ensure your .env file has the Azure OpenAI credentials.")
        sys.exit(1)

    logger.info("===========================================")
    logger.info("Agentic Orchestrator Pipeline Started")
    logger.info("===========================================")
    
    import argparse
    parser = argparse.ArgumentParser(description="Agentic Modernization Pipeline")
    parser.add_argument("--source-lang", default="java", help="Source language to modernize")
    parser.add_argument("--target-framework", default="java_springboot", help="Target framework to generate")
    args = parser.parse_args()

    # Initialize the LangGraph Supervisor
    orchestrator = create_orchestrator_agent()
    
    user_instruction = (
        f"Initiate the legacy {args.source_lang} codebase modernization pipeline for the 'legacy_source' directory.\n"
        "Strictly follow this execution sequence:\n"
        "1. Route to 'Ingestion' to fully index the codebase into ChromaDB.\n"
        "2. Once Ingestion completes, route to 'Documentation' to generate Markdown files into the 'documentation/' directory.\n"
        "3. Once Documentation completes, route to 'Evaluation' to grade the docs, isolating failures in 'flagged_documents/'.\n"
        "4. If Evaluation flagged documents, route to 'HumanReview' to pause for human intervention.\n"
        "5. Once Evaluation (and HumanReview if applicable) completes, route to 'Aggregation' to merge passing docs into 'master_docs/'.\n"
        "6. Once Aggregation completes, route to 'Architecture' to generate system architecture.\n"
        f"7. Once Architecture completes, route to 'CodeGeneration' to generate modernized {args.target_framework} code in 'modernized_source/'.\n"
        "8. Once CodeGeneration completes, route to 'TestGeneration' to generate functional unit tests.\n"
        "9. Route to 'FINISH' ONLY after the TestGeneration step has reported its completion summary."
    )
    
    inputs = {
        "messages": [HumanMessage(content=user_instruction)],
        "source_lang": args.source_lang,
        "target_framework": args.target_framework,
        "target_lang": args.target_framework.split('_')[0] if '_' in args.target_framework else args.target_framework
    }
    
    # Use a specific thread_id for checkpointing
    config_dict = {"configurable": {"thread_id": "main_pipeline_run_2"}}
    
    try:
        # Stream the graph execution
        for s in orchestrator.stream(inputs, config=config_dict, stream_mode="values"):
            if "messages" in s and s["messages"]:
                message = s["messages"][-1]
                if getattr(message, "name", None):
                    logger.info(f"\n--- Finished: {message.name} ---")
                    logger.info(message.content)
                elif isinstance(message, HumanMessage):
                    logger.info(f"\n--- User Instruction ---")
                    logger.info(message.content)
            if "next_node" in s:
                if s["next_node"] == "FINISH":
                    logger.info(f"\n[Supervisor] Task complete. Terminating graph.")
                else:
                    logger.info(f"\n[Supervisor Decision] Routing to: {s['next_node']}")

        logger.info("\n===========================================")
        logger.info("Workflow completed successfully!")
    except Exception as e:
        logger.error(f"\n[FATAL ERROR] Pipeline crashed: {e}")
        sys.exit(1)
