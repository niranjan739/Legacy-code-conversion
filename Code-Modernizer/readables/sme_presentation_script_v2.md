# J2J Legacy Code Modernizer — SME Presentation Script (V2)

> **How to use this document:** Read this from top to bottom as a spoken walkthrough. Every section flows into the next. Code snippets are included at the right moments to back up what you are saying. You do not need to read the code snippets aloud — they are there so you can point to them if the SME asks "show me where."

---

## Opening — What This Application Does

Let me start with the big picture before we go into any technical details.

We have a problem: large legacy Java codebases are expensive and risky to maintain. Manually reading through thousands of lines of old Java code, understanding what each class does, documenting it, and then rewriting it in modern Spring Boot takes weeks or months of senior developer time.

This application automates that entire process end to end. You point it at a folder of legacy `.java` files, run it, and it produces two things:

1. **A structured Markdown documentation library** — every class and method is explained in plain English with metadata.
2. **A compilable, modern Spring Boot Java project** — the modernized version of your legacy code, ready to build with Maven.

It does this using a chain of AI agents that pass work to each other in a controlled sequence, supervised by an orchestrator that decides what happens next. And importantly, it includes a premium **Human-in-the-Loop Dashboard** for you to oversee the process and fix anything the AI gets wrong.

---

## The Entry Point — Where Does It All Begin?

The primary way to run the pipeline is through **`agentic_main.py`** — our LangGraph orchestrator.

When you run `python agentic_main.py`, the very first thing it does is validate that the Azure OpenAI credentials are present in the environment. If they are missing, it exits immediately.

After that, it does three things in order:

1. It calls `create_orchestrator_agent()` to build the entire workflow graph.
2. It writes a natural language instruction that tells the pipeline what to do.
3. It starts streaming execution through the graph.

```python
# agentic_main.py
orchestrator = create_orchestrator_agent()

user_instruction = (
    "Initiate the legacy Java codebase modernization pipeline...\n"
    "1. Route to 'Ingestion'...\n"
    "2. Route to 'Documentation'...\n"
    "3. Route to 'Evaluation'...\n"
    "4. Route to 'Aggregation'...\n"
    "5. Route to 'CodeGeneration'...\n"
    "6. Route to 'FINISH' ONLY after CodeGeneration has completed."
)

inputs = {"messages": [HumanMessage(content=user_instruction)]}
config_dict = {"configurable": {"thread_id": "main_pipeline_run_2"}}

for s in orchestrator.stream(inputs, config=config_dict, stream_mode="values"):
    ...
```

The `thread_id` is important — it is the key used to save the pipeline's progress to a SQLite database so that if it crashes, it can resume from where it left off.

---

## The Foundation — Config and Utilities

Before we look at the agents, let me quickly walk you through two supporting files that everything else depends on.

### `config.py` — The Central Configuration File

Every directory path, every database path, and the LLM factory function all live here. No path is hardcoded anywhere else in the codebase.

```python
# config.py
LEGACY_SOURCE_DIR    = "legacy_source"       # Input: old Java files
DOCUMENTATION_DIR    = "documentation"        # Output: per-chunk Markdown docs
FLAGGED_DIR          = "flagged_documents"    # Failed evaluations
MASTER_DOCS_DIR      = "master_docs"          # Aggregated docs for code gen
MODERNIZED_SOURCE_DIR = "modernized_source"  # Final Spring Boot output
CHROMA_DB_DIR        = "./chroma_db"          # Vector database location
SQLITE_DB_PATH       = "state_checkpoint.db" # Graph checkpoint database
AUDIT_REPORT_PATH    = "audit_report.json"    # QA audit report
```

It also contains a single factory function for creating the LLM. Every agent calls this instead of creating its own Azure client. This ensures all agents use exactly the same parameters (temperature=0, max_retries=6).

---

## The Orchestrator — The Brain of the Application

**File:** `agents/orchestrator_agent.py`  

The orchestrator is a **LangGraph StateGraph** — a graph of nodes connected by edges, where each node is a step in the pipeline. Think of it as a sophisticated flowchart where a Supervisor AI decides which step to run next.

### Fully Autonomous vs. Workflow-Determined Workflows

This is an important concept to understand about this application.

**A fully autonomous workflow** is one where an AI agent decides everything on its own — what to do next, which tools to use, when to stop — with no developer-defined sequence. 

**A workflow-determined workflow** is the opposite — the developer explicitly writes code that defines every step, every connection, every condition. 

**This application is a Hybrid** — it uses both approaches deliberately:

| Decision | Who Makes It |
|---|---|
| Which nodes exist in the pipeline | **Developer** — hardcoded via `workflow.add_node()` |
| Which edges connect those nodes | **Developer** — hardcoded via `workflow.add_edge()` |
| Which node runs next at each step | **LLM** — the Supervisor reads history and decides |
| Which tools a ReAct agent calls | **LLM** — the agent reasons about what to do |
| How many chunks to process | **Developer** — deterministic Python `for` loop |
| Whether a document passes evaluation | **LLM** — the Evaluation Agent reasons and judges |

The developer constrains the *universe of valid choices*. The LLM makes the *actual selection* from that universe. This is the best of both worlds — structure and safety from the developer, intelligence and flexibility from the LLM.

### The Supervisor Node — The Routing Brain

The Supervisor does exactly three things every time it runs:

1. **Checks the step counter** — if more than 30 invocations have occurred, it forces a `FINISH` to prevent an infinite loop.
2. **Invokes the LLM** — sends the Supervisor's system prompt plus the full conversation history to Azure OpenAI. 
3. **Returns a routing decision** — forces the LLM to return exactly one of the valid node names (Ingestion, Documentation, Evaluation, Aggregation, CodeGeneration, FINISH).

---

## Agent 1 — The Ingestion Agent

It indexes the entire legacy codebase into a vector database so that future agents can semantically search it for context.

It uses a **Java-aware text splitter** to cut the files into 1,000-character chunks, trying to break at method and statement boundaries rather than cutting logic in half. It embeds these chunks into a local ChromaDB database.

---

## Agent 2 — The Documentation Agent

For every chunk (this time split into larger 10,000-character blocks for context), it writes a structured Markdown documentation file that explains the code in plain English.

Every Markdown file this agent writes must start with a YAML metadata block containing the original file path, a chunk ID, a confidence score, and external dependencies.

---

## Agent 3 — The Evaluation Agent and Audit Trail

It acts as a quality assurance reviewer. After every documentation chunk is written, the Evaluation Agent reads both the original Java code and the generated Markdown and decides: **Pass or Fail**.

### The Critical Difference — JSON Mode

Unlike the other agents, the Evaluation Agent's LLM is initialized with instructions to return a JSON object containing two keys: `"passed"` (boolean) and `"feedback"` (string).

### The Four Evaluation Criteria

1. Completeness:  Does the documentation cover the entire chunk provided?
2. Accuracy:      Are the descriptions technically correct based on the Java code?
3. Dependency:    Are external class calls properly identified and explained?
4. Traceability:  Is the origin clearly traceable via YAML frontmatter?

### Routing and the Audit Report

If the chunk **Passes**, it stays in the `documentation/` folder to be processed later.
If the chunk **Fails**, it is moved to `flagged_documents/` and will NOT be included in the code generation phase.

Furthermore, the pipeline records the outcome of *every single chunk* into **`audit_report.json`**. This provides a complete QA trail for stakeholders, showing exactly which files passed, which failed, and why.

---

## The Human-in-the-Loop Dashboard (`app.py`)

We do not just leave the failed documents behind. We have built a premium, glassmorphism-styled Streamlit Dashboard (`app.py`) to manage the workflow. 

It provides three tabs:
1. **Agentic Orchestrator**: You can launch the full end-to-end pipeline directly from the UI with a single click.
2. **Audit Report**: A clean dashboard view of the `audit_report.json` metrics, letting stakeholders instantly see how many chunks passed or failed, and expand the feedback blocks to read the AI's reasoning.
3. **Rework Flagged Docs**: If a chunk fails, the human reviewer can view it side-by-side with the Java code, type in some feedback (e.g., "You missed the FraudDetection check"), and click **Send for Rework**. The AI will rewrite the document based on your feedback and seamlessly merge it back into the main `documentation/` folder.

---

## Stage 4 — The Aggregation Agent

After evaluation and human refinement, the `documentation/` directory contains only perfect chunks. 

The Aggregator runs deterministically (no LLM). It concatenates all the individual chunk markdown files into a single, comprehensive Master Document for each Java class (`master_docs/<ClassName>_Master.md`).

---

## Stage 5 — The Code Generator

### Critical Point — What the Code Generator Reads

The Code Generator reads **only the Master Markdown Documents**. It does **not** have access to the original legacy `.java` files. Its entire understanding of the codebase comes from what the Documentation Agent wrote and what the human approved.

### The Three-Phase Process

1. **Architecture Planning**: It reads the Master Document and outputs a JSON list of exactly which `.java` files need to be created.
2. **Skeleton Generation + Auto-Healing**: It writes empty Java classes with method signatures. It then invokes Maven (`mvn clean compile`). If compilation fails, the compiler errors are sent back to the LLM, which autonomously fixes its own code and recompiles (up to 3 times).
3. **Logic Implementation**: Finally, it fills the business logic into the compiled skeletons, running the Maven auto-healer one more time to ensure a perfect build.

The final output is a completely functional, modern Spring Boot application in the `modernized_source/` directory!

---

## Frequently Asked Questions an SME Might Ask

**Q: What happens if the pipeline crashes in the middle?**
A: Because of the SQLite checkpointer, the entire state is saved after every single node. If you restart the script, LangGraph will restore the saved state and seamlessly resume from where it left off.

**Q: What happens if a chunk fails evaluation? Is it lost?**
A: No. It is moved to `flagged_documents/`. It will be temporarily excluded from Code Generation to prevent injecting bugs. You simply open the Streamlit Dashboard, provide feedback, and tell the AI to fix it. Once fixed, it goes back into the main pipeline.

**Q: Does the Code Generator see the original Java source?**
A: No. It only reads the Master Markdown documents. The quality of the generated code is entirely dependent on the quality of the documentation. This is why the Evaluation stage and the Human-in-the-Loop dashboard are so critical.

**Q: Can it process multiple Java files?**
A: Yes. It recursively scans the legacy directory and builds independent Master Documents for every class it finds.

**Q: What is the security concern with path sanitization?**
A: The LLM generates the output file path. A hallucinating LLM could potentially output a path like `../../etc/passwd`. Our `sanitize_path` utility function ensures that the resolved absolute path stays strictly inside the intended workspace directory.
