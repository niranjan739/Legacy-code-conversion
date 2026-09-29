# J2J Legacy Code Modernizer — SME Presentation Script

> **How to use this document:** Read this from top to bottom as a spoken walkthrough. Every section flows into the next. Code snippets are included at the right moments to back up what you are saying. You do not need to read the code snippets aloud — they are there so you can point to them if the SME asks "show me where."

---

## Opening — What This Application Does

Let me start with the big picture before we go into any technical details.

We have a problem: large legacy Java codebases are expensive and risky to maintain. Manually reading through thousands of lines of old Java code, understanding what each class does, documenting it, and then rewriting it in modern Spring Boot takes weeks or months of senior developer time.

This application automates that entire process end to end. You point it at a folder of legacy `.java` files, run it, and it produces two things:

1. **A structured Markdown documentation library** — every class and method is explained in plain English with metadata.
2. **A compilable, modern Spring Boot Java project** — the modernized version of your legacy code, ready to build with Maven.

It does this using a chain of AI agents that pass work to each other in a controlled sequence, supervised by an orchestrator that decides what happens next.

---

## The Entry Point — Where Does It All Begin?

The application has two ways to run:

- **`agentic_main.py`** — the full agentic version using LangGraph (recommended and what we will focus on)
- **`main.py`** — a simpler, procedural version of the same pipeline (no LangGraph orchestration)

When you run `python agentic_main.py`, the very first thing it does is validate that the Azure OpenAI credentials are present in the environment. If they are missing, it exits immediately.

```python
# agentic_main.py, lines 14–18
if __name__ == "__main__":
    if not os.environ.get("AZURE_OPENAI_KEY_GPT4o"):
        print("Warning: AZURE_OPENAI_KEY_GPT4o environment variable is not set.")
        sys.exit(1)
```

After that, it does three things in order:

1. It calls `create_orchestrator_agent()` to build the entire workflow graph.
2. It writes a natural language instruction that tells the pipeline what to do.
3. It starts streaming execution through the graph.

```python
# agentic_main.py, lines 25–45
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
config_dict = {"configurable": {"thread_id": "main_pipeline_run_1"}}

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
```

It also contains a single factory function for creating the LLM. Every agent calls this instead of creating its own Azure client. This ensures all agents use exactly the same parameters.

```python
# config.py, lines 13–29
def get_llm(temperature=0, response_format=None):
    kwargs = {
        "api_key":          os.environ.get("AZURE_OPENAI_KEY_GPT4o"),
        "azure_endpoint":   os.environ.get("AZURE_OPENAI_ENDPOINT"),
        "azure_deployment": os.environ.get("AZURE_OPENAI_DEPLOYMENT"),
        "api_version":      "2025-01-01-preview",
        "temperature":      temperature,
        "max_retries":      6
    }
    if response_format:
        kwargs["model_kwargs"] = {"response_format": response_format}
    return AzureChatOpenAI(**kwargs)
```

**Key LLM parameters:**
- `temperature=0` — zero randomness; deterministic, consistent outputs. Important for code generation.
- `max_retries=6` — if Azure throttles the request, the client automatically retries up to 6 times.
- `api_version="2025-01-01-preview"` — the Azure API version being used.
- Model name — comes from `AZURE_OPENAI_DEPLOYMENT` environment variable, not hardcoded. Assumed to be GPT-4o by naming convention.

### `utils.py` — Shared Utility Functions

Three utility functions used across the whole project:

```python
# utils.py
def setup_logger(name):         # Creates a timestamped logger for each component
def sanitize_path(base_dir, requested_path):  # Blocks path traversal attacks
def generate_chunk_id(index):   # Returns "chunk_01", "chunk_02", etc.
```

The `sanitize_path` function is a security control. Since the LLM decides the output file path for documentation, we cannot trust it blindly. This function ensures the LLM cannot write files outside the intended `documentation/` directory — for example, it blocks paths like `../../etc/passwd`.

---

## The Orchestrator — The Brain of the Application

Now let us get into the heart of the application.

**File:** `agents/orchestrator_agent.py`  
**Function:** `create_orchestrator_agent()`

The orchestrator is a **LangGraph StateGraph** — a graph of nodes connected by edges, where each node is a step in the pipeline. Think of it as a sophisticated flowchart where a Supervisor AI decides which step to run next.

---

### Understanding the State — The Application's Memory

Before we talk about nodes and edges, we need to understand **state**. State is the shared memory that the entire graph reads from and writes to.

```python
# orchestrator_agent.py, lines 27–30
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next_node: str
    steps: int
```

There are exactly three fields:

| Field | Type | Purpose |
|---|---|---|
| `messages` | List of messages | The full conversation history — every agent's completion summary is added here. The Supervisor reads this to understand what has been done so far. |
| `next_node` | String | The name of the next node to run. Set by the Supervisor LLM after reading `messages`. |
| `steps` | Integer | A counter that increments every time the Supervisor runs. Used as a safety valve — if it exceeds 30, the pipeline forces a `FINISH` to prevent infinite loops. |

The `operator.add` annotation on `messages` is critical. It means that every time a node writes to `messages`, the new message is **appended** to the list rather than replacing it. This builds up a conversation history that the Supervisor can read like a log of everything that has happened.

**Important distinction — State vs. Data:**

The state does *not* carry Java code, documentation content, or generated files. Those large pieces of data flow through the **filesystem**. The state only carries short summary strings like "Documentation Agent finished processing 35 chunks." This keeps the state lean and SQLite-storable.

---

### Fully Autonomous vs. Workflow-Determined Workflows

This is an important concept to understand about this application.

**A fully autonomous workflow** is one where an AI agent decides everything on its own — what to do next, which tools to use, when to stop — with no developer-defined sequence. The developer just says "solve this problem" and the agent figures out the entire plan.

**A workflow-determined workflow** is the opposite — the developer explicitly writes code that defines every step, every connection, every condition. There is no AI involved in the workflow control at all. It is like a traditional ETL pipeline.

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

---

### Where Are the Nodes Created?

All six node functions are created as **nested functions inside `create_orchestrator_agent()`** in `orchestrator_agent.py`. They are defined at these exact lines:

```python
# orchestrator_agent.py
def supervisor_node(state: AgentState):     ...  # line 62
def ingestion_node(state: AgentState):      ...  # line 74
def documentation_node(state: AgentState):  ...  # line 85
def evaluation_node(state: AgentState):     ...  # line 124
def aggregation_node(state: AgentState):    ...  # line 190
def code_generation_node(state: AgentState): ... # line 199
```

They are nested inside `create_orchestrator_agent()` deliberately — this gives them access to the `llm` object and `config` values through Python's closure mechanism, without needing to pass them as arguments.

---

### How Are Nodes Added to the Orchestrator?

After the node functions are defined, they are registered with the `StateGraph` object using `workflow.add_node()`:

```python
# orchestrator_agent.py, lines 209–216
workflow = StateGraph(AgentState)

workflow.add_node("Supervisor",     supervisor_node)
workflow.add_node("Ingestion",      ingestion_node)
workflow.add_node("Documentation",  documentation_node)
workflow.add_node("Evaluation",     evaluation_node)
workflow.add_node("Aggregation",    aggregation_node)
workflow.add_node("CodeGeneration", code_generation_node)
```

The first argument is the string name of the node (used in routing), and the second is the Python function to execute when that node is activated.

---

### How Are Edges Added?

Edges tell LangGraph what happens after each node finishes.

**Static Edges (lines 219–223):** All five worker nodes always return to the Supervisor after completing their work. This is the "hub and spoke" pattern.

```python
workflow.add_edge("Ingestion",      "Supervisor")
workflow.add_edge("Documentation",  "Supervisor")
workflow.add_edge("Evaluation",     "Supervisor")
workflow.add_edge("Aggregation",    "Supervisor")
workflow.add_edge("CodeGeneration", "Supervisor")
```

**Conditional Edges (lines 228–239):** The Supervisor's output is dynamic, so we use a conditional edge. The `lambda` reads `state["next_node"]` and uses it as a key to look up the destination.

```python
workflow.set_entry_point("Supervisor")

workflow.add_conditional_edges(
    "Supervisor",
    lambda state: state["next_node"],   # reads the routing string
    {
        "Ingestion":      "Ingestion",
        "Documentation":  "Documentation",
        "Evaluation":     "Evaluation",
        "Aggregation":    "Aggregation",
        "CodeGeneration": "CodeGeneration",
        "FINISH":         END              # LangGraph's terminal sentinel
    }
)
```

**Entry Point:** The graph always starts at the Supervisor (`workflow.set_entry_point("Supervisor")`).

**Compilation:** After all nodes and edges are registered, the graph is compiled with a SQLite checkpointer:

```python
# orchestrator_agent.py, lines 241–243
conn = sqlite3.connect(config.SQLITE_DB_PATH, check_same_thread=False)
memory = SqliteSaver(conn)
return workflow.compile(checkpointer=memory)
```

This checkpointer saves the full `AgentState` to `state_checkpoint.db` after every single node execution. If the application crashes, you can restart it with the same `thread_id` and it will resume from the last saved state.

---

### The Supervisor Node — The Routing Brain

```python
# orchestrator_agent.py, lines 62–72
def supervisor_node(state: AgentState):
    current_steps = state.get("steps", 0)
    
    if current_steps > 30:
        logger.warning("[Orchestrator] Max steps exceeded. Forcing FINISH.")
        return {"next_node": "FINISH", "steps": current_steps + 1}
        
    supervisor_chain = prompt | llm.with_structured_output(Route)
    result = supervisor_chain.invoke(state)
    return {"next_node": result.next_node, "steps": current_steps + 1}
```

The Supervisor does exactly three things every time it runs:

1. **Checks the step counter** — if more than 30 Supervisor invocations have occurred, something is wrong, and it forces a `FINISH` to prevent an infinite loop.
2. **Invokes the LLM** — sends the Supervisor's system prompt plus the full `messages` history to Azure OpenAI. The LLM reads the history like a journal and decides what has been done and what should happen next.
3. **Returns a routing decision** — the `with_structured_output(Route)` call forces the LLM to return exactly one of the valid node names, not free text. This is the Pydantic model that enforces this:

```python
# orchestrator_agent.py, lines 33–36
class Route(BaseModel):
    next_node: str = Field(
        description="Options are: 'Ingestion', 'Documentation', 'Evaluation', 'Aggregation', 'CodeGeneration', or 'FINISH'."
    )
```

The Supervisor's system prompt explicitly tells the LLM the strict sequential order it must follow:

```python
# orchestrator_agent.py, lines 41–53
system_prompt = (
    "You are an Agentic Orchestrator managing a legacy Java modernization pipeline.\n"
    "Route strictly sequentially: Ingestion → Documentation → Evaluation → Aggregation → CodeGeneration → FINISH.\n"
    "Only output 'FINISH' after 'CodeGeneration' has reported completion.\n"
)
```

---

## How Chunking Works

Before we walk through the agents, we need to understand chunking because it affects nearly every stage.

The legacy Java files can be very large — tens of thousands of lines. You cannot send an entire file to an LLM at once because it would exceed the context window limit. So the application splits each file into smaller, manageable pieces called chunks.

The tool used is `RecursiveCharacterTextSplitter.from_language(language=Language.JAVA)` from LangChain.

**Why Java-language-aware splitting?** The `from_language(Language.JAVA)` setting makes the splitter aware of Java syntax. It first tries to split at class boundaries, then at method boundaries, then at statement separators, and only as a last resort at raw character counts. This means chunks are far more likely to contain complete methods rather than being cut in the middle of a method body.

**Two different chunk sizes are used:**

### Configuration 1: For the Vector Database (Ingestion)

```python
# ingestion_agent.py, lines 33–37
java_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.JAVA,
    chunk_size=1000,     # ~1,000 characters per chunk
    chunk_overlap=100    # 100 characters overlap between chunks
)
docs = java_splitter.create_documents([code], metadatas=[{"source": file_path}])
```

- **1,000 characters** per chunk — small, precise chunks optimized for semantic search. When the Documentation Agent searches the codebase for an unknown class or method, it wants to find the most relevant short piece of code, not a huge block.
- Each chunk carries `{"source": file_path}` metadata so you always know which file it came from.
- These chunks are embedded (converted to numerical vectors) using `FastEmbedEmbeddings` and stored in **ChromaDB**.

### Configuration 2: For Documentation and Evaluation (Agent Processing)

```python
# orchestrator_agent.py, lines 89–91
java_splitter = RecursiveCharacterTextSplitter.from_language(
    language=Language.JAVA,
    chunk_size=10000,    # ~10,000 characters per chunk
    chunk_overlap=1000   # 1,000 characters overlap
)
```

- **10,000 characters** per chunk — larger chunks that fit comfortably within GPT-4o's context window while covering meaningful logical units of the codebase (e.g., a full service class with all its methods).
- **1,000-character overlap** ensures that code near a chunk boundary has enough surrounding context in both the current and the next chunk.
- Chunks are numbered using `generate_chunk_id(i)` → `chunk_01`, `chunk_02`, etc.
- These chunk text strings are passed directly in the `HumanMessage` to the Documentation and Evaluation agents.

**Important:** The two chunk configurations are different. The 1,000-char embedding chunks and the 10,000-char processing chunks are not the same. This means a search for context returns small precise snippets, while the agent processes larger meaningful blocks.

---

## Agent 1 — The Ingestion Agent

**File:** `agents/ingestion_agent.py`  
**Type:** ReAct Agent (created via `langgraph.prebuilt.create_react_agent`)

### What Is a ReAct Agent?

Before describing each agent, let me explain what a ReAct agent is, because three of our five pipeline stages use this pattern.

A ReAct agent is a reasoning-action loop. The LLM receives a task. It then reasons: "What tool should I call to make progress?" It calls the tool, reads the result, and reasons again. It keeps doing this until it decides it is done. The developer provides a fixed set of tools — the LLM autonomously decides the order and combination of calls.

### What the Ingestion Agent Does

It indexes the entire legacy codebase into a vector database so that future agents can semantically search it for context.

### Tools Available to the Ingestion Agent

```python
# ingestion_agent.py, lines 17–54
@tool
def list_files_in_directory(directory_path: str) -> list[str]:
    """Lists all Java files in the specified directory."""
    # Uses glob.glob to find all *.java files recursively

@tool
def chunk_and_embed_file(file_path: str) -> str:
    """Reads a Java file, chunks it, and stores embeddings in ChromaDB."""
    # Splits into 1,000-char chunks with Java splitter
    # De-duplicates: deletes existing embeddings for this file before inserting
    # Adds documents to ChromaDB with source metadata
```

**De-duplication logic (important):** Before inserting new chunks, the agent queries ChromaDB for any existing chunks from the same file and deletes them. This prevents the database from growing unboundedly on repeated runs.

```python
# ingestion_agent.py, lines 41–46
existing = vector_store.get(where={"source": file_path})
if existing and existing.get("ids"):
    vector_store.delete(ids=existing["ids"])
```

### Ingestion Agent System Prompt

```python
# ingestion_agent.py, lines 61–67
system_prompt = """
You are an autonomous Codebase Ingestion Agent.
Your job is to index legacy codebases so that other agents can search them later.
When given a directory, you should first list all the files in it.
Then, iterate through those files and use the chunk_and_embed_file tool on each of them.
Report back when all files have been successfully embedded.
"""
```

### Ingestion Agent — Input and Output

**Input:** The original user instruction `HumanMessage` from `agentic_main.py`, which contains the directory name (`legacy_source`). This is passed directly from `state["messages"][0]`.

```python
# orchestrator_agent.py, lines 79–81
for chunk in agent.stream({"messages": [state["messages"][0]]}, stream_mode="values"):
    result_text = chunk["messages"][-1].content
```

**Output:** An `AIMessage` with `name="Ingestion"` containing a text summary like `"Ingestion Agent finished: Successfully embedded N chunks from..."`. This message is appended to `AgentState.messages`.

**Side effect:** ChromaDB vector store at `./chroma_db/` is populated with embedded chunks.

### LLM Parameters for Ingestion Agent
- Provider: Azure OpenAI
- `temperature=0`
- `max_retries=6`
- No JSON mode
- No `max_tokens` configured

---

## Agent 2 — The Documentation Agent

**File:** `agents/documentation_agent.py`  
**Type:** ReAct Agent

### What the Documentation Agent Does

For every chunk of every Java file, it writes a structured Markdown documentation file that explains the code in plain English.

### How the Documentation Loop Works

This is crucial to understand. The Documentation Agent is **not called once**. It is called in a loop — once per chunk of every Java file. The outer Python loop is in `documentation_node` inside `orchestrator_agent.py`:

```python
# orchestrator_agent.py, lines 85–122
def documentation_node(state: AgentState):
    agent = create_doc_agent()
    java_files = glob.glob(f"{config.LEGACY_SOURCE_DIR}/**/*.java", recursive=True)
    java_splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.JAVA, chunk_size=10000, chunk_overlap=1000
    )
    
    for java_file in java_files:
        code = open(java_file, 'r', encoding='utf-8').read()
        chunks = java_splitter.split_text(code)
        base_name = os.path.basename(java_file).replace('.java', '')
        
        for i, chunk_text in enumerate(chunks):
            chunk_id = generate_chunk_id(i)   # "chunk_01", "chunk_02", ...
            doc_instruction = (
                f"Read this chunk from '{java_file}'. "
                f"Generate markdown documentation and write it to "
                f"'{config.DOCUMENTATION_DIR}/{base_name}/{chunk_id}.md'.\n"
                f"Code:\n```java\n{chunk_text}\n```"
            )
            inputs = {"messages": [HumanMessage(content=doc_instruction)]}
            
            for _ in agent.stream(inputs, stream_mode="values"):
                pass   # run agent until complete
                
            time.sleep(1)   # rate limit buffer
```

Each invocation of the agent gets its own fresh `HumanMessage` with:
1. The source file path (so the agent can read more context if needed)
2. The exact target output path (`documentation/ClassName/chunk_01.md`)
3. The actual Java source chunk text

### Tools Available to the Documentation Agent

```python
# documentation_agent.py
@tool
def read_java_file(file_path: str) -> str:
    """Reads and returns the contents of a Java file."""
    # Used if the agent wants to read the full file for extra context

@tool
def write_documentation(file_path: str, content: str) -> str:
    """Writes Markdown documentation to the specified file path."""
    # Sanitizes the path first to block path traversal
    safe_path = sanitize_path(os.getcwd(), file_path)
    os.makedirs(os.path.dirname(safe_path), exist_ok=True)
    with open(safe_path, 'w', encoding='utf-8') as f:
        f.write(content)

@tool
def search_codebase(query: str) -> str:
    """Searches ChromaDB for code chunks matching the query."""
    # Returns top-3 semantically similar chunks
    results = vector_store.similarity_search(query, k=3)
    # Also includes a 3-second sleep to respect rate limits
```

### Documentation Agent System Prompt

```python
# documentation_agent.py, lines 67–84
system_prompt = """
You are an autonomous expert technical writer and Java developer.
Your task is to read a chunk of a legacy Java codebase, generate well-structured
Markdown documentation for it, and save the documentation.

IMPORTANT METADATA REQUIREMENT:
Every Markdown file MUST begin with a YAML frontmatter block:
---
original_file: "path/to/file.java"
language: "Java"
chunk_id: "<generate_a_unique_id>"
confidence_score: <score_between_0.0_and_1.0>
external_dependencies: [<list_of_external_classes>]
---

If you encounter unknown methods or classes, use the search_codebase tool
to find their definitions before writing the documentation.
"""
```

### The YAML Frontmatter Schema

Every Markdown file this agent writes must start with this header block:

| Field | Description |
|---|---|
| `original_file` | Path to the source `.java` file |
| `language` | Always `"Java"` |
| `chunk_id` | A unique identifier the LLM generates |
| `confidence_score` | The LLM's self-assessment of how well it understood the code (0.0 to 1.0) |
| `external_dependencies` | List of external classes or services this chunk depends on |

This YAML header is later used by the Evaluation Agent to check **Traceability** — can we trace this documentation back to its source?

### Documentation Agent — Input and Output

**Input per invocation:**
- A `HumanMessage` containing the source Java chunk text (up to 10,000 characters) and the target output file path.

**Output:**
- A `.md` file written to `documentation/<ClassName>/chunk_NN.md` containing YAML frontmatter + Markdown explanation.
- A brief confirmation string returned to the node.

**Example output file path:** `documentation/DemoApplication/chunk_01.md`

### LLM Parameters for Documentation Agent
- Provider: Azure OpenAI  
- `temperature=0`
- `max_retries=6`
- No JSON mode — the agent produces free-form Markdown

---

## Agent 3 — The Evaluation Agent

**File:** `agents/evaluation_agent.py`  
**Type:** ReAct Agent — but with **JSON mode enabled**

### What the Evaluation Agent Does

It acts as a quality assurance reviewer. After every documentation chunk is written, the Evaluation Agent reads both the original Java code and the generated Markdown and decides: **Pass or Fail**.

### The Critical Difference — JSON Mode

```python
# evaluation_agent.py, line 35
llm = config.get_llm(response_format={"type": "json_object"})
```

Unlike the other agents, the Evaluation Agent's LLM is initialized with `response_format={"type": "json_object"}`. This forces Azure OpenAI to **always return a valid JSON object**, never free text. This is essential because the orchestrator's Python code `json.loads()` the response — if the LLM returned plain text, the pipeline would crash.

### How the Evaluation Loop Works

Same structure as documentation — it loops over the same chunks:

```python
# orchestrator_agent.py, lines 124–188
def evaluation_node(state: AgentState):
    agent = create_eval_agent()
    # Same chunking (10,000/1,000) applied to same java files
    
    for java_file in java_files:
        for i, chunk_text in enumerate(chunks):
            chunk_id = generate_chunk_id(i)
            doc_path = f"{config.DOCUMENTATION_DIR}/{base_name}/{chunk_id}.md"
            
            if os.path.exists(doc_path):
                generated_doc = open(doc_path, 'r', encoding='utf-8').read()
                
                eval_instruction = (
                    f"Evaluate the following documentation against the source Java chunk.\n"
                    f"Source Java Chunk:\n```java\n{chunk_text}\n```\n"
                    f"Generated Documentation:\n```markdown\n{generated_doc}\n```"
                )
                eval_inputs = {"messages": [HumanMessage(content=eval_instruction)]}
                
                eval_response = ""
                for eval_chunk in agent.stream(eval_inputs, stream_mode="values"):
                    eval_response = eval_chunk["messages"][-1].content
```

Each Evaluation Agent invocation receives:
1. The original Java source chunk
2. The exact Markdown file that was generated for that chunk

### The Four Evaluation Criteria

```python
# evaluation_agent.py, lines 39–56
system_prompt = """
You must grade the documentation on a Pass/Fail scale based on 4 criteria:

1. Completeness:  Does the documentation cover the entire chunk provided?
2. Accuracy:      Are the descriptions technically correct based on the Java code?
3. Dependency:    Are external class calls properly identified and explained?
4. Traceability:  Is the origin (file and chunk) clearly traceable via YAML frontmatter?

You MUST output your final evaluation as a JSON object with exactly two keys:
{
  "passed": true or false,
  "feedback": "Your detailed feedback and reasons here"
}
"""
```

### The Pass/Fail Decision and File Routing

```python
# orchestrator_agent.py, lines 160–180
try:
    eval_json = json.loads(eval_response)
    passed = eval_json.get("passed", False)   # default to False if key missing
except json.JSONDecodeError:
    logger.error("Failed to parse Evaluation Agent response as JSON.")
    passed = False   # fail-safe: if JSON is broken, treat as failed

if not passed:
    # Move the file to flagged_documents/ and prepend the feedback
    flagged_dir  = f"{config.FLAGGED_DIR}/{base_name}"
    flagged_path = f"{flagged_dir}/{chunk_id}.md"
    with open(flagged_path, 'w', encoding='utf-8') as f:
        f.write(f"<!-- EVALUATOR FEEDBACK:\n{eval_response}\n-->\n\n{generated_doc}")
    os.remove(doc_path)   # remove from documentation/
else:
    # Leave the file in documentation/ — it will be picked up by Aggregation
    pass
```

**PASS:** The Markdown file stays in `documentation/` and will be picked up by the Aggregation Agent.  
**FAIL:** The Markdown file is moved to `flagged_documents/`, and the Evaluation Agent's feedback is prepended as an HTML comment so a developer can read exactly why it failed.

### Evaluation Agent — Input and Output

**Input per invocation:**
- `HumanMessage` containing the original Java chunk text AND the generated Markdown documentation (both provided together).

**Output:**
```json
{
  "passed": true,
  "feedback": "Documentation is complete, accurate, all dependencies identified, and YAML frontmatter present."
}
```

**Side effect:** Failed `.md` files moved from `documentation/` to `flagged_documents/`.

### LLM Parameters for Evaluation Agent
- Provider: Azure OpenAI
- `temperature=0`
- `max_retries=6`
- **`response_format={"type": "json_object"}` — JSON mode enabled**
- One tool available: `search_codebase` (to verify accuracy against ChromaDB)

---

## Stage 4 — The Aggregation Agent

**File:** `agents/aggregator_agent.py`  
**Function:** `run_aggregator()`  
**Type:** NOT an AI agent — pure deterministic Python function

### What It Does and Why

After evaluation, the `documentation/` directory contains only the chunks that **passed** quality review. Now we need to combine them into complete, class-level documents that the Code Generator can understand holistically.

This stage deliberately uses no LLM. Every word in the Master Document is exactly what the Documentation Agent wrote. There is zero risk of the LLM summarizing, paraphrasing, or hallucinating during aggregation.

```python
# aggregator_agent.py, lines 8–49
def run_aggregator():
    class_dirs = os.listdir(config.DOCUMENTATION_DIR)
    
    for c_dir in class_dirs:
        md_files = glob.glob(f"{config.DOCUMENTATION_DIR}/{c_dir}/*.md")
        md_files.sort()   # ensures chunk_01 comes before chunk_02
        
        all_content = []
        for f_path in md_files:
            all_content.append(open(f_path, 'r', encoding='utf-8').read())
            
        combined_content = "\n\n=== NEXT CHUNK ===\n\n".join(all_content)
        
        master_path = os.path.join(config.MASTER_DOCS_DIR, f"{c_dir}_Master.md")
        with open(master_path, "w", encoding="utf-8") as f:
            f.write(f"# MASTER DOCUMENT: {c_dir}\n\n")
            f.write(combined_content)
```

### Aggregation — Input and Output

**Input:** All passing `.md` files in `documentation/<ClassName>/` (sorted alphabetically by `chunk_NN`)

**Output:** One `master_docs/<ClassName>_Master.md` file per class, containing all chunks concatenated with `=== NEXT CHUNK ===` separators.

**No LLM called. No tools used. 100% data retention.**

---

## Stage 5 — The Code Generator

**File:** `agents/code_generator_agent.py`  
**Function:** `run_code_generation()`  
**Type:** NOT a ReAct agent — a sequential orchestrator of direct LLM calls with a Maven compilation loop

### Critical Point — What the Code Generator Reads

The Code Generator reads **only the Master Markdown Documents from `master_docs/`**. It does **not** have access to the original legacy `.java` files. Its entire understanding of the codebase comes from what the Documentation Agent wrote.

This is why documentation quality matters so much — garbage documentation produces garbage code.

### Spring Boot Project Initialization (happens once)

Before any code is written, the application downloads a fresh Spring Boot starter project from `start.spring.io`:

```python
# code_generator_agent.py, lines 14–45
def init_spring_boot_project(target_dir):
    url = "https://start.spring.io/starter.zip"
    params = {
        "type":        "maven-project",
        "language":    "java",
        "groupId":     "com.example",
        "artifactId":  "demo",
        "packageName": "com.example.demo",
        "javaVersion": "21",
        "dependencies": "web,lombok"
    }
    response = requests.get(url, params=params)
    # Saves and extracts the zip into modernized_source/
```

This gives the project its `pom.xml`, Maven Wrapper (`mvnw`/`mvnw.cmd`), and standard directory structure. All generated Java files go into `modernized_source/src/main/java/com/example/demo/`.

### The Three-Phase Code Generation Process

For each Master Document file:

---

#### Phase 1 — Architecture Planning (LLM with JSON mode)

```python
# code_generator_agent.py, lines 136–152
plan_system = """You are a Principal Software Architect. Read the Master Document
and determine the exact Spring Boot Java files needed.
Return a strictly formatted JSON: {"files": ["DemoApplication.java", "UserService.java"]}"""

plan_response = llm.invoke([
    SystemMessage(content=plan_system),
    HumanMessage(content=master_content)
])
plan = json.loads(plan_response.content)
files_to_generate = plan.get("files", [])
```

**LLM:** JSON mode  
**Input:** Full Master Markdown Document  
**Output:** `{"files": ["FileName1.java", "FileName2.java", ...]}` — the list of Java files to create

---

#### Phase 1.5 — Skeleton Generation + Compilation Healing

For each filename the planner identified:

```python
# code_generator_agent.py, lines 157–163
skeleton_system = """You are a Senior Java Developer specializing in Spring Boot 3.x and Java 21.
Write ONLY the SKELETON class for the requested file.
Include: package, imports, class annotations, field declarations, method signatures.
DO NOT WRITE BUSINESS LOGIC. Leave all methods empty (return null, 0, or false).
Use package com.example.demo; Use Lombok where appropriate.
CRITICAL RULE: One class per file. Do NOT define multiple classes in the same file.
Return ONLY the raw Java code. No markdown code blocks."""
```

After all skeletons are written, Maven is invoked to compile:

```python
# code_generator_agent.py, lines 60–63
result = subprocess.run(
    [mvn_cmd, "clean", "compile"],
    cwd=target_dir,
    capture_output=True,
    text=True,
    timeout=300   # 5-minute timeout
)
```

If compilation fails, the **Auto-Healer** kicks in (up to 3 attempts):

```python
# code_generator_agent.py, lines 82–107
fixer_system = """You are an Expert Java Debugger.
Return a JSON: {"files": [{"filename": "X.java", "fixed_code": "..."}]}"""

fixer_prompt = f"Compiler Errors:\n{compressed_error}\n\nCurrent Source Code:\n{current_files}"

fix_response = llm.invoke([SystemMessage(content=fixer_system), HumanMessage(content=fixer_prompt)])
fix_plan = json.loads(fix_response.content)

for f in fix_plan.get("files", []):
    file_path = sanitize_path(java_src_dir, f["filename"])   # security check
    with open(file_path, "w") as fw:
        fw.write(f["fixed_code"])
```

**Compiler error compression (important detail):** Only the top 50 error lines are sent to the LLM to avoid context overflow:
```python
error_lines = [line for line in error_output.split("\n") if "[ERROR]" in line]
compressed_error = "\n".join(error_lines[:50])
```

---

#### Phase 2 — Logic Implementation

Once the skeletons compile cleanly, Phase 2 fills in the actual business logic:

```python
# code_generator_agent.py, lines 199–209
logic_system = """You are a Senior Java Developer specializing in Spring Boot 3.x.
Fill in the business logic for a specific file.
You have the Master Document and the complete compiling SKELETON project context.
Write the FULL and EXHAUSTIVE complete Java code.
Do NOT change method signatures from the skeleton.
Return ONLY raw Java code."""

prompt = (
    f"Master Document:\n{master_content}\n\n"
    f"All Healed Skeletons Context:\n{healed_skeletons}\n\n"
    f"Task: Write the FULL IMPLEMENTED code for {filename}."
)
```

**Key design choice:** Phase 2 sends both the Master Document AND the already-compiled skeleton code as context. This means the LLM knows the exact method signatures it must implement, reducing type errors and signature mismatches.

After Phase 2, Maven is invoked again (Phase 2.5 Auto-Healing) — up to 3 more compile-fix cycles.

### Fallback for Skeleton Generation Failure

If the LLM call for a skeleton completely fails, a stub class is written so compilation can still attempt:

```python
# code_generator_agent.py, lines 176–177
raw_code = f"package com.example.demo;\npublic class {filename.replace('.java','')} {{}}"
```

### Code Generator — Input and Output

**Input:** `master_docs/<ClassName>_Master.md` (Markdown documentation only — no original Java source)

**Output:** `modernized_source/src/main/java/com/example/demo/*.java` — fully implemented, Maven-compilable Spring Boot Java files.

**LLM Parameters:**
- `llm` (planning and healing): JSON mode, `temperature=0`, `max_retries=6`
- `code_llm` (skeleton and logic): No JSON mode, `temperature=0`, `max_retries=6`
- Maven subprocess timeout: **300 seconds (5 minutes)**
- Auto-healer max retries: **3 compilation attempts**

---

## How Nodes, State, and Edges Work Together — The Full Picture

Let me tie everything together with a single end-to-end trace.

```
START
│
agentic_main.py
│  Creates inputs = {"messages": [HumanMessage("...pipeline instruction...")]}
│  thread_id = "main_pipeline_run_1"
│
▼
Supervisor Node (Step 1)
│  Reads: messages[0] = user instruction
│  LLM decides: "Ingestion"
│  Writes: next_node="Ingestion", steps=1
│  State saved to SQLite
│
▼
Ingestion Node
│  create_ingestion_agent() → ReAct agent
│  Agent lists files → chunk_and_embed_file (1,000/100 chars) → ChromaDB
│  Returns: AIMessage(name="Ingestion", content="...finished...")
│  State: messages=[HumanMessage, AIMessage(Ingestion)]
│
▼
Supervisor Node (Step 2)
│  Reads full messages list, sees Ingestion complete
│  LLM decides: "Documentation"
│  Writes: next_node="Documentation", steps=2
│
▼
Documentation Node
│  Loops: For each .java file → split (10,000/1,000) → per-chunk ReAct agent
│  Each agent invocation: write_documentation tool → documentation/Class/chunk_NN.md
│  Returns: AIMessage(name="Documentation", content="...35 chunks...")
│  State: messages=[HumanMessage, AIMessage(Ingestion), AIMessage(Documentation)]
│
▼
Supervisor Node (Step 3)
│  Sees Documentation complete
│  LLM decides: "Evaluation"
│
▼
Evaluation Node
│  Same loop: For each chunk → load .md → eval_agent (JSON mode)
│  Each agent: returns {"passed": bool, "feedback": "..."}
│  PASS: file stays in documentation/
│  FAIL: file moved to flagged_documents/ with feedback comment
│  Returns: AIMessage(name="Evaluation", content="...35 files...")
│
▼
Supervisor Node (Step 4) → "Aggregation"
▼
Aggregation Node
│  run_aggregator(): pure Python, no LLM
│  Sorts + concatenates passing .md files per class
│  Writes: master_docs/ClassName_Master.md
│  Returns: AIMessage(name="Aggregation")
│
▼
Supervisor Node (Step 5) → "CodeGeneration"
▼
CodeGeneration Node
│  run_code_generation():
│    1. Download Spring Boot project from start.spring.io
│    2. Phase 1: Plan architecture (JSON LLM) → list of Java files
│    3. Phase 1.5: Write skeletons → mvn compile → auto-heal (x3)
│    4. Phase 2: Fill logic → mvn compile → auto-heal (x3)
│  Writes: modernized_source/src/main/java/com/example/demo/*.java
│  Returns: AIMessage(name="CodeGeneration")
│
▼
Supervisor Node (Step 6)
│  Reads all messages, sees CodeGeneration complete
│  LLM decides: "FINISH"
│
▼
END (LangGraph terminal)
│
State saved: state_checkpoint.db contains full run history
```

---

## Frequently Asked Questions an SME Might Ask

**Q: What happens if the pipeline crashes in the middle?**

A: Because of the `SqliteSaver` checkpointer, the entire `AgentState` (including all messages) is saved after every single node. If you restart `agentic_main.py` with the same `thread_id = "main_pipeline_run_1"`, LangGraph will restore the saved state and the Supervisor will read the message history to determine where to continue from.

**Q: What happens if a chunk fails evaluation? Is it lost?**

A: It is moved to `flagged_documents/<ClassName>/chunk_NN.md` with the evaluator's feedback prepended as an HTML comment. Currently the pipeline continues without that chunk — it will not appear in the Master Document or the generated code. This is an architectural gap where a self-healing refinement loop could be added.

**Q: Does the Code Generator see the original Java source?**

A: No. It only reads the Master Markdown documents. The quality of the generated code is entirely dependent on the quality of the documentation. This is why the Documentation and Evaluation stages are so critical.

**Q: Can it process multiple Java files?**

A: Yes. `glob.glob("legacy_source/**/*.java", recursive=True)` finds all Java files in any subdirectory. The Aggregator creates one Master Document per class/file name.

**Q: Why is `temperature=0` used for all agents?**

A: Zero temperature makes the LLM deterministic — it always picks the highest-probability token rather than sampling randomly. For code generation and documentation, we want consistent, reproducible outputs. Creative variability would be counterproductive.

**Q: What is the security concern with `sanitize_path`?**

A: The Documentation Agent's LLM generates the output file path. A malicious or hallucinating LLM could potentially output a path like `../../etc/passwd` or `C:\Windows\System32\file.exe`. The `sanitize_path` function checks that the resolved absolute path stays inside the intended base directory and rejects any path with `..` components or absolute paths.

---

## Summary Table — All Agents at a Glance

| Agent | Type | LLM Called? | Tools | Input | Output | LLM Mode |
|---|---|---|---|---|---|---|
| Supervisor | Node | Direct invoke | None | Full `AgentState` | `next_node` string | Structured output (`Route`) |
| Ingestion | ReAct Agent | Via ReAct | `list_files`, `chunk_and_embed_file` | User instruction | ChromaDB populated | Default |
| Documentation | ReAct Agent | Via ReAct | `read_java_file`, `write_documentation`, `search_codebase` | Java chunk text | `.md` files in `documentation/` | Default |
| Evaluation | ReAct Agent | Via ReAct | `search_codebase` | Java chunk + `.md` file | `{"passed": bool}` + file move | **JSON mode** |
| Aggregation | Python function | **No** | None | `.md` files | `master_docs/*.md` | N/A |
| Code Generator | Direct LLM calls | Direct invoke | Maven subprocess | Master `.md` files | Spring Boot `.java` project | JSON + Default |

| Parameter | Value | Configured In |
|---|---|---|
| LLM Provider | Azure OpenAI | `config.py` |
| Model | `AZURE_OPENAI_DEPLOYMENT` env var | `.env` file |
| Temperature | `0` | `config.py:22` |
| Max Retries | `6` | `config.py:23` |
| API Version | `2025-01-01-preview` | `config.py:21` |
| Embedding chunk size | `1,000` chars / `100` overlap | `ingestion_agent.py:35–36` |
| Processing chunk size | `10,000` chars / `1,000` overlap | `orchestrator_agent.py:90` |
| Auto-healer retries | `3` | `code_generator_agent.py:49` |
| Maven timeout | `300 seconds` | `code_generator_agent.py:60` |
| Max Supervisor steps | `30` | `orchestrator_agent.py:66` |
