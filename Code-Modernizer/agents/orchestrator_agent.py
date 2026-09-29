import os
import glob
import time
import json
from typing import TypedDict, Annotated, Sequence
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, Field
from utils.ast_splitter import ASTSplitter
from utils.language_profiles import SOURCE_PROFILES, TARGET_PROFILES

from agents.ingestion_agent import create_ingestion_agent
from agents.documentation_agent import create_doc_agent
from agents.evaluation_agent import create_eval_agent
from agents.aggregator_agent import run_aggregator
from agents.architecture_agent import run_architecture_generation
from agents.code_generator_agent import run_code_generation
from agents.test_generation_agent import run_test_generation
import config
from utils import setup_logger, generate_chunk_id

logger = setup_logger("Orchestrator")

# Define the State for our Agentic Orchestrator
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next_node: str
    steps: int
    rework_count: int
    flagged_chunks: list[str]
    source_lang: str
    target_lang: str
    target_framework: str

# Define the structured output for the Supervisor
class Route(BaseModel):
    next_node: str = Field(
        description="The next agent to route to. Options are: 'Ingestion', 'Documentation', 'Evaluation', 'HumanReview', 'Aggregation', 'Architecture', 'CodeGeneration', 'TestGeneration', or 'FINISH'."
    )

def create_orchestrator_agent():
    llm = config.get_llm()
    
    system_prompt = (
        "You are an Agentic Orchestrator (Supervisor) managing a strict, sequential multi-agent RAG and modernization pipeline for a legacy Java codebase.\n"
        "You must route execution through specialized teams in a specific order. Do NOT deviate from this workflow or hallucinate steps.\n\n"
        "TEAMS AND RESPONSIBILITIES:\n"
        "1. 'Ingestion': Scans source, chunks it, embeds it.\n"
        "2. 'Documentation': Iterates through chunks, writes Markdown.\n"
        "3. 'Evaluation': QA agent. Grades Markdown.\n"
        "4. 'HumanReview': If Evaluation fails, human steps in here to fix it.\n"
        "5. 'Aggregation': Combines passing docs into Master Documents.\n"
        "6. 'Architecture': Generates high-level system architecture from Master Docs.\n"
        "7. 'CodeGeneration': Generates modernized code from Master Docs.\n"
        "8. 'TestGeneration': Generates and runs functional tests.\n\n"
        "ROUTING RULES:\n"
        "- Route strictly sequentially: Ingestion -> Documentation -> Evaluation -> (HumanReview if flagged) -> Aggregation -> Architecture -> CodeGeneration -> TestGeneration -> FINISH.\n"
        "- EXCEPTION: If Evaluation flags chunks, route to 'HumanReview' so the human can intervene.\n"
        "- Only output 'FINISH' after 'TestGeneration' completes.\n"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="messages"),
        ("system", "Given the conversation above, who should act next? Respond with exactly one of: Ingestion, Documentation, Evaluation, HumanReview, Aggregation, Architecture, CodeGeneration, TestGeneration, FINISH")
    ])
    
    def supervisor_node(state: AgentState):
        current_steps = state.get("steps", 0)
        
        # Max iteration guard
        if current_steps > 30:
            logger.warning("[Orchestrator] Max steps exceeded. Forcing FINISH.")
            return {"next_node": "FINISH", "steps": current_steps + 1}
            
        supervisor_chain = prompt | llm.with_structured_output(Route)
        result = supervisor_chain.invoke(state)
        return {"next_node": result.next_node, "steps": current_steps + 1}
        
    def ingestion_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Ingestion Agent...")
        agent = create_ingestion_agent()
        
        source_lang = state.get("source_lang", "java")
        profile = SOURCE_PROFILES.get(source_lang, SOURCE_PROFILES["java"])
        
        instruction = state["messages"][0].content
        instruction += f"\n\nSource Extension: {profile['extension']}\nSplitter Language: {profile['splitter_language']}"
        
        result_text = ""
        for chunk in agent.stream({"messages": [HumanMessage(content=instruction)]}, stream_mode="values"):
            result_text = chunk["messages"][-1].content
            
        return {"messages": [AIMessage(content=f"Ingestion Agent finished: {result_text}", name="Ingestion")]}

    def architecture_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Architecture Agent...")
        result_text = run_architecture_generation(state)
        return {"messages": [AIMessage(content=result_text, name="Architecture")]}

    def human_review_node(state: AgentState):
        logger.info("\n[Orchestrator] Human Review complete. Resuming pipeline...")
        return {"messages": [AIMessage(content="Human Review approved.", name="HumanReview")]}

    def documentation_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Documentation Agent...")
        agent = create_doc_agent()
        
        source_lang = state.get("source_lang", "java")
        profile = SOURCE_PROFILES.get(source_lang, SOURCE_PROFILES["java"])
        ext = profile["extension"]
        splitter_lang = profile["splitter_language"]
        
        java_files = glob.glob(f"{config.LEGACY_SOURCE_DIR}/**/*{ext}", recursive=True)
        java_splitter = ASTSplitter(language=splitter_lang)
        
        flagged_chunks = state.get("flagged_chunks", [])
        is_rework = len(flagged_chunks) > 0
        
        doc_results = []
        for java_file in java_files:
            try:
                with open(java_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                chunks = java_splitter.split_text(code)
                base_name = os.path.basename(java_file).replace('.java', '')
                
                for i, chunk_text in enumerate(chunks):
                    chunk_id = generate_chunk_id(i)
                    file_chunk_id = f"{base_name}/{chunk_id}.md"
                    
                    if is_rework and file_chunk_id not in flagged_chunks:
                        continue
                        
                    target_path = f"{config.DOCUMENTATION_DIR}/{base_name}/{chunk_id}.md"
                    if not is_rework and os.path.exists(target_path):
                        logger.info(f"  -> Skipping {file_chunk_id}, already exists (Resumability).")
                        continue
                        
                    logger.info(f"  -> Agent generating doc for {file_chunk_id}")
                    doc_instruction = (
                        f"Read this chunk from '{java_file}'. "
                        f"Generate markdown documentation and write it to '{config.DOCUMENTATION_DIR}/{base_name}/{chunk_id}.md'.\n"
                        f"Code:\n```java\n{chunk_text}\n```"
                    )
                    inputs = {"messages": [HumanMessage(content=doc_instruction)]}
                    
                    if is_rework:
                        flagged_path = f"{config.FLAGGED_DIR}/{file_chunk_id}"
                        if os.path.exists(flagged_path):
                            with open(flagged_path, 'r', encoding='utf-8') as f:
                                flagged_content = f.read()
                            doc_instruction += f"\n\nThis chunk was previously FLAGGED by evaluation. Feedback:\n{flagged_content}"
                            inputs = {"messages": [HumanMessage(content=doc_instruction)]}
                            os.remove(flagged_path)
                    
                    # Run the doc agent for this chunk
                    for _ in agent.stream(inputs, stream_mode="values"):
                        pass
                    
                    doc_results.append(f"Documented {base_name}/{chunk_id}.md")
                    time.sleep(1) # Prevent rate limits
            except Exception as e:
                logger.error(f"Error documenting {java_file}: {e}")
                doc_results.append(f"Error documenting {java_file}: {e}")
                
        summary = f"Documentation Agent finished processing {len(doc_results)} chunks."
        return {"messages": [AIMessage(content=summary, name="Documentation")]}

    def evaluation_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Evaluation Agent...")
        agent = create_eval_agent()
        
        source_lang = state.get("source_lang", "java")
        profile = SOURCE_PROFILES.get(source_lang, SOURCE_PROFILES["java"])
        ext = profile["extension"]
        splitter_lang = profile["splitter_language"]
        
        java_files = glob.glob(f"{config.LEGACY_SOURCE_DIR}/**/*{ext}", recursive=True)
        java_splitter = ASTSplitter(language=splitter_lang)
        
        eval_results = []
        audit_log = []
        for java_file in java_files:
            try:
                with open(java_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                chunks = java_splitter.split_text(code)
                base_name = os.path.basename(java_file).replace('.java', '')
                
                for i, chunk_text in enumerate(chunks):
                    chunk_id = generate_chunk_id(i)
                    doc_path = f"{config.DOCUMENTATION_DIR}/{base_name}/{chunk_id}.md"
                    
                    if os.path.exists(doc_path):
                        logger.info(f"  -> Agent evaluating {base_name}/{chunk_id}")
                        with open(doc_path, 'r', encoding='utf-8') as f:
                            generated_doc = f.read()
                            
                        eval_instruction = (
                            f"Evaluate the following documentation against the source Java chunk.\n"
                            f"Source Java Chunk:\n```java\n{chunk_text}\n```\n"
                            f"Generated Documentation:\n```markdown\n{generated_doc}\n```"
                        )
                        eval_inputs = {"messages": [HumanMessage(content=eval_instruction)]}
                        
                        eval_response = ""
                        for eval_chunk in agent.stream(eval_inputs, stream_mode="values"):
                            eval_response = eval_chunk["messages"][-1].content
                            
                        # Parse structured JSON output
                        try:
                            clean_response = eval_response.strip()
                            if clean_response.startswith("```json"):
                                clean_response = clean_response[7:]
                            if clean_response.endswith("```"):
                                clean_response = clean_response[:-3]
                            eval_json = json.loads(clean_response.strip())
                            passed = eval_json.get("passed", False)
                        except json.JSONDecodeError:
                            logger.error(f"Failed to parse Evaluation Agent response as JSON: {eval_response}")
                            passed = False # Default to fail if parsing error
                            
                        if not passed:
                            flagged_dir = f"{config.FLAGGED_DIR}/{base_name}"
                            os.makedirs(flagged_dir, exist_ok=True)
                            flagged_path = f"{flagged_dir}/{chunk_id}.md"
                            
                            with open(flagged_path, 'w', encoding='utf-8') as f:
                                f.write(f"<!-- EVALUATOR FEEDBACK:\n{eval_response}\n-->\n\n{generated_doc}")
                            os.remove(doc_path)
                            eval_results.append(f"Flagged {base_name}/{chunk_id}.md")
                            logger.info(f"     [FAIL] Moved to flagged_documents")
                            audit_log.append({
                                "chunk_id": chunk_id,
                                "source_file": java_file,
                                "status": "flagged",
                                "feedback": eval_response
                            })
                        else:
                            eval_results.append(f"Passed {base_name}/{chunk_id}.md")
                            logger.info(f"     [PASS]")
                            audit_log.append({
                                "chunk_id": chunk_id,
                                "source_file": java_file,
                                "status": "passed",
                                "feedback": eval_response
                            })
                            
                        time.sleep(1) # Prevent rate limits
            except Exception as e:
                logger.error(f"Error evaluating {java_file}: {e}")
                eval_results.append(f"Error evaluating {java_file}: {e}")
                
        try:
            with open(config.AUDIT_REPORT_PATH, 'w', encoding='utf-8') as f:
                json.dump(audit_log, f, indent=2)
            logger.info(f"Wrote audit report to {config.AUDIT_REPORT_PATH}")
        except Exception as e:
            logger.error(f"Failed to write audit report: {e}")

        flagged_list = [r.split(' ')[1] for r in eval_results if 'Flagged' in r]
        summary = f"Evaluation Agent finished. Processed {len(eval_results)} files. {len(flagged_list)} chunks flagged."
        return {
            "messages": [AIMessage(content=summary, name="Evaluation")],
            "flagged_chunks": flagged_list,
            "rework_count": state.get("rework_count", 0) + 1 if flagged_list else 0
        }
        
    def aggregation_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Aggregation Agent...")
        try:
            summary = run_aggregator()
        except Exception as e:
            logger.error(f"Error during aggregation: {e}")
            summary = f"Error during aggregation: {e}"
        return {"messages": [AIMessage(content=summary, name="Aggregation")]}
        
    def code_generation_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Code Generation Agent...")
        try:
            summary = run_code_generation(state)
        except Exception as e:
            logger.error(f"Error during code generation: {e}")
            summary = f"Error during code generation: {e}"
        return {"messages": [AIMessage(content=summary, name="CodeGeneration")]}

    def test_generation_node(state: AgentState):
        logger.info("\n[Orchestrator] Launching Test Generation Agent...")
        from agents.test_generation_agent import run_test_generation
        try:
            summary = run_test_generation(state)
        except Exception as e:
            logger.error(f"Error during test generation: {e}")
            summary = f"Error during test generation: {e}"
        return {"messages": [AIMessage(content=summary, name="TestGeneration")]}

    # Compile the StateGraph
    builder = StateGraph(AgentState)
    
    builder.add_node("Supervisor", supervisor_node)
    builder.add_node("Ingestion", ingestion_node)
    builder.add_node("Documentation", documentation_node)
    builder.add_node("Evaluation", evaluation_node)
    builder.add_node("HumanReview", human_review_node)
    builder.add_node("Aggregation", aggregation_node)
    builder.add_node("Architecture", architecture_node)
    builder.add_node("CodeGeneration", code_generation_node)
    builder.add_node("TestGeneration", test_generation_node)
    
    # All worker nodes report back to the Supervisor
    builder.add_edge("Ingestion", "Supervisor")
    builder.add_edge("Documentation", "Supervisor")
    builder.add_edge("Evaluation", "Supervisor")
    builder.add_edge("HumanReview", "Supervisor")
    builder.add_edge("Aggregation", "Supervisor")
    builder.add_edge("Architecture", "Supervisor")
    builder.add_edge("CodeGeneration", "Supervisor")
    builder.add_edge("TestGeneration", "Supervisor")
    
    builder.set_entry_point("Supervisor")
    
    # The Supervisor decides what to do next based on the state
    builder.add_conditional_edges(
        "Supervisor",
        lambda state: state["next_node"],
        {
            "Ingestion": "Ingestion",
            "Documentation": "Documentation",
            "Evaluation": "Evaluation",
            "HumanReview": "HumanReview",
            "Aggregation": "Aggregation",
            "Architecture": "Architecture",
            "CodeGeneration": "CodeGeneration",
            "TestGeneration": "TestGeneration",
            "FINISH": END
        }
    )
    
    memory = SqliteSaver.from_conn_string(config.SQLITE_DB_PATH)
    return builder.compile(checkpointer=memory, interrupt_before=["HumanReview", "CodeGeneration"])
