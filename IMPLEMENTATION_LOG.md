# TestPulse — Implementation Log

> Tracks the engineering progression of TestPulse across all development milestones.
> Updated upon completion of every milestone following the verification protocol in `.agents/rules/RULES.md`.

---

## Milestone 0: Repository Foundation, Project Constitution & Ephemeral Sandbox Baseline

**Status**: Completed  
**Date**: 2026-10-19  
**Goal**: Establish the repository foundation, project constitutions, engineering rules, directory structure, native host runtime environment, SQLite database with WAL mode, Qdrant Local lazy open/close architecture, FastAPI baseline endpoints, ephemeral Docker sandbox image, and initial test suite.

### Key Decisions & Guardrails Implemented
1. **Host-Native Engine on Windows 11**: FastAPI, LangGraph, and MCP server run natively in host Python `.venv`. Docker is used strictly for ephemeral sandboxes and live app stacks.
2. **Client Repository Inviolability**: Read-only mount (`:ro`) into sandboxes; all test files, snapshots, and execution logs reside strictly in internal directories (`.testpulse/`, `runs/`).
3. **Component 1 Strict Backend Scope**: Anchored to Python/FastAPI/SQLite. No frontend React unit tests or JSDOM mocks.
4. **SQLite Concurrency & WAL Mode**: Configured `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` via SQLAlchemy event listeners to allow concurrent access by FastAPI and MCP servers without lock contention.
5. **Qdrant Local Lazy Pattern**: Open and close `QdrantClient(path=".testpulse/qdrant")` per operation; zero global singleton or startup open locks.
6. **Pre-Baked Offline Sandbox**: Pre-installed the full FastAPI stack (`fastapi`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `aiosqlite`, `sqlmodel`, `pytest`, `pytest-cov`, `pytest-asyncio`, `httpx`) inside `Dockerfile.sandbox-python` for hermetic `--network="none"` execution.
7. **Sandbox SQLite Write Safety**: Enforced `TESTPULSE_SANDBOX_DB_PATH=/tmp/test_sqlite.db` and `PYTHONDONTWRITEBYTECODE=1` inside test sandboxes to avoid `sqlite3.OperationalError` against read-only mounts.
8. **Configurable Sandbox Memory**: Sandboxes default to 2GB RAM cap via `TESTPULSE_SANDBOX_MEMORY_LIMIT`, expandable as needed to prevent premature OOM failures.
9. **Uncompromised LLM Test Quality**: Configurable model tiers via `.env` (`TESTPULSE_TIER1_MODELS`, `TESTPULSE_TIER2_MODELS`); paid OpenRouter tier supported as needed to guarantee deep verification without sacrificing QA thoroughness.
10. **Full Anti-Shallow Validation Discipline**:
    - **Gate 1 (Static AST Test-Smell Detection)**: Tree-sitter scan rejecting zero assertions, trivial tautologies (`assert x is not None`), conditional assertions (in `if` blocks), and mock abuse.
    - **Sandbox Execution & Coverage Ratchet**: Ephemeral Docker run requiring `exit_code == 0` and strict coverage of Planner's target lines.
    - **Exit Code Routing**: If `exit_code != 0`, bypass mutation and route to Problem A (test fault repair loop, max 3 retries) vs. Problem B (application defect finding report).
    - **Gate 2 (Targeted Mutation Testing)**: Inject 2–3 logic mutations into a sandbox copy; mutants must be killed.
    - **Flakiness & Fail-to-Pass Checks**: Multi-run randomized checks for integration tests; fail-on-buggy / pass-on-fixed for regression tests.
11. **Graphify Local Integration**: Multi-language AST extraction and graph construction adapted and vendored directly into `src/testpulse/graph/` from a local clone of the official repository (`https://github.com/Graphify-Labs/graphify`); no external API calls.

### Deliverables Created
- **Constitutions & Rules**:
  - `AGENTS.md`: Authoritative contract with 10 Inviolable Laws, architecture overview, and tech stack.
  - `.agents/rules/RULES.md`: Codified engineering standards, SQLite WAL pattern, Qdrant lazy pattern, sandbox execution rules, LLM routing, and verification protocols.
  - `.agents/skills/repo-indexing/SKILL.md`: Repo ingestion, AST extraction, and Qdrant Local RAG workflow.
  - `.agents/skills/test-strategy/SKILL.md`: Strategy profiles (unit, integration, regression) and provenance tracking.
  - `.agents/skills/sandbox-execution/SKILL.md`: Hermetic Docker sandbox execution flags and write safety.
  - `.agents/skills/milestone-completion/SKILL.md`: Sign-off checklist and verification protocol.
- **Project Configuration**:
  - `pyproject.toml`: Complete build configuration and dependencies.
  - `.env.example`: Comprehensive environment template with LLM model tiers, embeddings, paths, and sandbox settings.
  - `.gitignore`: Production-grade ignore rules.
  - `README.md`: System overview and quickstart instructions.
- **Docker Infrastructure**:
  - `docker/Dockerfile.sandbox-python`: Pre-baked Python 3.11-slim sandbox image with FastAPI testing stack.
- **Application Source (`src/testpulse/`)**:
  - `src/testpulse/__init__.py`: Package root.
  - `src/testpulse/main.py`: FastAPI server with async lifespan and SQLite initialization.
  - `src/testpulse/api/__init__.py`, `health.py`, `runs.py`: REST routes for health monitoring and run status stubs.
  - `src/testpulse/core/__init__.py`, `config.py`: Centralized `pydantic-settings` configuration with path validators.
  - `src/testpulse/models/__init__.py`, `database.py`, `schemas.py`: SQLAlchemy async models (Run, Snapshot, TestPlan, GeneratedTest, Finding, BrowserSession, RCAReport) with WAL mode event listener, plus Pydantic v2 schemas.
- **Automated Tests (`tests/`)**:
  - `tests/__init__.py`, `tests/conftest.py`: Async pytest fixtures with isolated temporary SQLite WAL database and HTTP client.
  - `tests/unit/__init__.py`
  - `tests/unit/test_health.py`: Unit tests for `/`, `/health`, and `/runs/`.
  - `tests/unit/test_database.py`: Unit tests for SQLite WAL pragmas, busy_timeout, CRUD, and cascade deletion.

### Verification Output
- **Ruff Linter**:
  ```
  .\.venv\Scripts\ruff.exe check .
  All checks passed!
  ```
- **Automated Tests**:
  ```
  .\.venv\Scripts\pytest.exe tests/ -v
  tests/unit/test_database.py::test_sqlite_wal_and_busy_timeout PASSED [ 16%]
  tests/unit/test_database.py::test_create_and_query_run PASSED        [ 33%]
  tests/unit/test_database.py::test_run_cascade_deletion PASSED        [ 50%]
  tests/unit/test_health.py::test_root_endpoint PASSED                 [ 66%]
  tests/unit/test_health.py::test_health_check_endpoint PASSED         [ 83%]
  tests/unit/test_health.py::test_runs_stub_endpoint PASSED            [100%]
  6 passed in 0.36s
  ```
- **Constitution Compliance**:
  - All 10 Inviolable Laws observed.
  - SQLite WAL mode and busy timeout verified via unit tests.
  - Architecture plan artifact updated with user feedback.

### Limitations & Next Steps
- Milestone 0 established the baseline architecture, data models, schemas, and ephemeral container specification.
- Next target was Milestone 1.

---

## Milestone 1: Native In-House AST Graph Engine with Human-Readable Reporting

**Status**: Completed  
**Date**: 2026-10-20  
**Goal**: Build the native in-house AST graph engine inside `src/testpulse/graph/`, adapting Tree-sitter AST traversal, 2-pass cross-file resolution, and topological queries from local inspection of Graphify (`https://github.com/Graphify-Labs/graphify`), while implementing TestPulse enhancements: deterministic normalized `sha256_ast_body_hash` calculation, cyclomatic branching complexity counting, FastAPI route decorator and `Depends(...)` injection detection, unit target ranking with trivial getter filtering, 2-hop regression blast radius computation, graph diffing with logic drift tracking, human-readable Markdown reporting (`GRAPH_REPORT.md`), and interactive HTML graph visualization.

### Key Architectural Decisions & Enhancements
1. **Local Graphify Adaptation**: Cloned `https://github.com/Graphify-Labs/graphify.git` into `.vendor/graphify` (git-ignored) strictly for source inspection. Stripped all CLI bloat, benchmark runners, remote wiki/html servers, and 37 non-target language extractors. Built an in-house engine specialized strictly for Python (FastAPI/SQLite) and JS/TS.
2. **Deterministic AST Body Hashes**: Implemented `calculate_ast_body_hash` which normalizes whitespace and strips standalone docstrings and line/inline comments before computing SHA-256. This detects internal algorithmic and constant modifications even when method signatures and call graph edges remain unchanged.
3. **Directed Knowledge Graph (`nx.DiGraph`)**: Constructed a native directed graph allowing bidirectional traversals: `G.predecessors` for callers and `G.successors` for downstream dependencies.
4. **FastAPI Route & Dependency Extraction**: Built `entry_points.py` to inspect Tree-sitter decorator AST nodes (`@app.get`, `@router.post`, etc.), extracting HTTP method, route path, and injected `Depends(...)` service providers.
5. **Anti-Shallow Unit Target Filtering**: `select_unit_targets(G)` calculates a composite score based on cyclomatic complexity and topological centrality, while strictly filtering out trivial getters and passthrough wrappers (`cyclomatic_complexity <= 1` and `< 6` lines).
6. **2-Hop Blast Radius & Logic Drift Diffing**: `compute_graph_diff` identifies structural changes and logic hash drift, calculating an immediate regression blast radius ($ModifiedNodes \cup Callers^2 \cup Dependencies^1$) for targeted testing.
7. **Comprehensive Human-Readable Reporting**: `reporter.py` compiles a clean Markdown document (`GRAPH_REPORT.md`) detailing scanned modules, detected FastAPI entry points, God nodes and prioritized business logic, filtered trivial functions, and circular import cycle warnings.

### Deliverables Created
- **Internal Vendor Reference**:
  - `.vendor/graphify`: Local clone of Graphify repository for inspection.
- **Graph Engine (`src/testpulse/graph/`)**:
  - `src/testpulse/graph/ast_extractor.py`: Multi-language Tree-sitter AST extractor with cyclomatic complexity calculation and noise built-in filtering.
  - `src/testpulse/graph/ast_hasher.py`: Normalized SHA-256 AST body hasher.
  - `src/testpulse/graph/entry_points.py`: FastAPI route decorator and dependency injection detector.
  - `src/testpulse/graph/cross_file_resolver.py`: 2-pass edge resolution (EXTRACTED containment/imports/Depends vs INFERRED call resolution).
  - `src/testpulse/graph/graph_builder.py`: NetworkX DiGraph builder, `graph.json` and `ast_hashes.json` persistence.
  - `src/testpulse/graph/queries.py`: Topological queries (`god_nodes`, `find_import_cycles`, `select_unit_targets`, `select_integration_targets`, `compute_blast_radius`).
  - `src/testpulse/graph/diff.py`: `GraphDiff` engine combining structural additions/removals with AST body hash drift.
  - `src/testpulse/graph/reporter.py`: Markdown `GRAPH_REPORT.md` generator and force-directed HTML visualization.
  - `src/testpulse/graph/__init__.py`: Public package exports.
- **Fixtures & Tests (`tests/`)**:
  - `tests/fixtures/sample_fastapi/`: Multi-file FastAPI fixture (`main.py`, `routes/orders.py`, `services/discount_service.py`, `models/order.py`) with business logic, deliberate discount calculation defect, and trivial getters.
  - `tests/unit/test_graph.py`: 11 comprehensive unit tests covering AST parsing, hashing, entry points, cross-file resolution, trivial getter filtering, blast radius, graph diffing, and report generation.

### Verification Output
- **Ruff Linter**:
  ```
  .\.venv\Scripts\ruff.exe check .
  All checks passed!
  ```
- **Pyright Static Type Checker**:
  ```
  .\.venv\Scripts\pyright.exe src/ tests/
  0 errors, 0 warnings, 0 informations
  ```
- **Automated Test Suite**:
  ```
  .\.venv\Scripts\pytest.exe tests/ -v
  tests/unit/test_database.py::test_sqlite_wal_and_busy_timeout PASSED     [  5%]
  tests/unit/test_database.py::test_create_and_query_run PASSED            [ 11%]
  tests/unit/test_database.py::test_run_cascade_deletion PASSED            [ 17%]
  tests/unit/test_graph.py::test_scan_and_ast_extraction PASSED            [ 23%]
  tests/unit/test_graph.py::test_ast_hasher_normalization_and_drift PASSED [ 29%]
  tests/unit/test_graph.py::test_fastapi_entry_point_detection PASSED      [ 35%]
  tests/unit/test_graph.py::test_cross_file_resolution PASSED              [ 41%]
  tests/unit/test_graph.py::test_select_unit_targets_filters_trivial_getters PASSED [ 47%]
  tests/unit/test_graph.py::test_select_integration_targets PASSED         [ 52%]
  tests/unit/test_graph.py::test_compute_blast_radius PASSED               [ 58%]
  tests/unit/test_graph.py::test_graph_diff_with_ast_hash_drift PASSED     [ 64%]
  tests/unit/test_graph.py::test_graph_serialization PASSED                [ 70%]
  tests/unit/test_graph.py::test_god_nodes_and_cycle_detection PASSED      [ 76%]
  tests/unit/test_graph.py::test_report_and_html_generation PASSED         [ 82%]
  tests/unit/test_health.py::test_root_endpoint PASSED                     [ 88%]
  tests/unit/test_health.py::test_health_check_endpoint PASSED             [ 94%]
  tests/unit/test_health.py::test_runs_stub_endpoint PASSED                [100%]
  17 passed in 1.15s
  ```
- **Live Graph Report**:
  Generated and verified at `.testpulse/GRAPH_REPORT.md`.

### Limitations & Next Steps
- Tree-sitter AST extraction is tailored specifically to Python and JS/TS; other languages are deferred behind the architecture interface.
- Graph edges currently represent static and inferred calls; dynamic `getattr` and eval are deliberately out of scope.
- Next target: **Milestone 2 — Code-Aware RAG with Qdrant Local Mode (Lazy Open/Close)**.

---

## Milestone 2: Code-Aware RAG with Qdrant Local Mode (Lazy Open/Close)

**Status**: Completed  
**Date**: 2026-10-21  
**Goal**: Implement the code-aware RAG subsystem inside `src/testpulse/rag/` combining AST graph knowledge with semantic text indexing and dual-pipeline retrieval, strictly enforcing remote-only embeddings (zero host RAM for PyTorch/transformers) and the lazy open/close lifecycle on Qdrant Local Mode (`.testpulse/qdrant`) to prevent database locks.

### Key Architectural Decisions & Guardrails Implemented
1. **Centralized Trivial Function Helper**: Refactored `is_trivial_function` / `is_trivial_node` and `get_node_line_count` into `src/testpulse/graph/queries.py` and exported them across the graph package, centralizing the anti-shallow cyclomatic complexity ($\le 1$) and line count ($< 6$) filter across unit target ranking and reporter generation.
2. **Dual-Strategy Chunker (`chunker.py`)**:
   - **AST Code Chunking (1 Node = 1 Chunk)**: Extracts exact source lines for all function, method, and class AST nodes from the directed knowledge graph (`G`), prepending a contextual cAST metadata header containing Node ID, source file, line span, and direct callers (e.g. `# Callers: create_order`).
   - **Descriptive File Chunking**: Recursively scans the workspace for Markdown documentation (`*.md`) and global test fixtures (`conftest.py`), splitting semantically by markdown headings (`# `, `## `, `### `) and injecting descriptive headers (`# Section: Business Rules`).
3. **Remote API Embedder (`embedder.py`)**:
   - Dispatches batch embedding requests via `litellm.embedding()` targeting `settings.embedding_model` using remote API credentials (`TESTPULSE_EMBEDDING_API_KEY` or `OPENROUTER_API_KEY`).
   - Strict adherence to the 16GB host RAM constraint: Zero local PyTorch, SentenceTransformers, or HuggingFace dependencies imported or loaded.
4. **Lazy Qdrant Indexer (`indexer.py`)**:
   - Enforces the **Critical File Lock Rule**: Every index operation instantiates `QdrantClient(path=...)` in Local Mode and immediately executes `client.close()` inside a `try/finally` block.
   - Prevents `database is locked` concurrency conflicts between background runs, FastAPI, and MCP servers.
   - Creates collection `testpulse_codebase` with Cosine distance and stores the exact string `node_id` as a filterable payload field with deterministic UUID5 point IDs.
5. **Dual-Pipeline Retriever (`retriever.py`)**:
   - **Pipeline A (Graph Walk — Exact Match)**: Discovers graph neighbors up to `hop_depth` (callers, class containers, dependencies) and executes a payload filter scroll against Qdrant Local.
   - **Pipeline B (Blindspot Sweeper — Semantic Match)**: Computes vector embedding for the target symbol's name and docstring, and executes semantic vector search (`client.query_points`) with a negative filter (`must_not`) excluding all nodes already gathered by Pipeline A. Successfully retrieves disconnected business rule documents (e.g., `README.md` rules).
   - Combines results into a unified context string separated by `\n\n---\n\n`.

### Deliverables Created
- **RAG Subsystem (`src/testpulse/rag/`)**:
  - `src/testpulse/rag/chunker.py`: Dual-strategy AST code and semantic markdown chunker with header injection.
  - `src/testpulse/rag/embedder.py`: Remote-only API embedding gateway with batching and zero host RAM footprint.
  - `src/testpulse/rag/indexer.py`: Lazy Qdrant Local indexer with strict `try/finally: client.close()` discipline.
  - `src/testpulse/rag/retriever.py`: Dual-pipeline context retriever combining graph walks with semantic blindspot sweeping.
  - `src/testpulse/rag/__init__.py`: Package root exporting public RAG functions.
- **Fixtures & Tests (`tests/`)**:
  - `tests/fixtures/sample_fastapi/README.md`: Added sample documentation detailing business rules (e.g., "Discounts cannot exceed 50%").
  - `tests/unit/test_rag.py`: 7 comprehensive unit tests verifying AST header injection, markdown section splitting, remote embedder batching, strict lazy Qdrant client lifecycle (immediate reopen test), dual-pipeline retrieval, and shorthand symbol resolution.

### Verification Output
- **Ruff Linter**:
  ```
  .\.venv\Scripts\ruff.exe check .
  All checks passed!
  ```
- **Pyright Static Type Checker**:
  ```
  .\.venv\Scripts\pyright.exe src/ tests/
  0 errors, 0 warnings, 0 informations
  ```
- **Automated Test Suite**:
  ```
  .\.venv\Scripts\pytest.exe tests/ -v
  24 passed in 8.65s (100% green)
  ```
- **Inviolable Law & Constitution Compliance**:
  - Client repository remained read-only.
  - Qdrant Local client strictly opened and closed per RAG operation (no startup locks).
  - Remote embeddings only (zero PyTorch/transformers in host RAM).

### Limitations & Next Steps
- Chunker currently indexes Python/JS/TS source code and Markdown descriptive text; multi-language adapters (e.g. SQL, Go) will hook into `chunk_repository` in future milestones.
- Next target: **Milestone 3 — Component 1: Context Gatherer & Test Planning Agent (Behavior Matrix & Coverage Ratchet)**.

---

## Milestone 3: Multi-Strategy Context Gatherer & Test Planning Agent (Component 1)

**Status**: Completed  
**Date**: 2026-10-23  
**Goal**: Implement the first two agents of the sequential 4-agent state machine (`ContextGatherer` $\to$ `TestPlanner`) inside `src/testpulse/pipeline/`, supporting all three testing strategies (Unit, Integration, Regression) with strict Pydantic v2 data contracts, resilient tiered LLM routing (failover on 429/503/timeout), clean dual-pipeline context separation, and anti-shallow BehaviorMatrix synthesis.

### Key Architectural Decisions & Guardrails Implemented
1. **Pydantic v2 Data Contracts (`src/testpulse/models/schemas.py`)**:
   - `StrategyType`: `Literal["unit", "integration", "regression"]`.
   - `ContextBundle`: Strictly separates `focal_code` (target AST node chunk), `dependency_code` (Pipeline A callers, callees, and container classes), `descriptive_context` (Pipeline B semantic sweeper, including business rules and README discount constraints), strategy-specific `mock_policy`, and workspace `existing_fixtures`.
   - `BehaviorCase`: Structured test scenario with normalized `category` (`Literal["happy", "boundary", "negative"]`), concrete inputs, and verifiable expected outcomes.
   - `BehaviorMatrix`: Explicit planning contract specifying target symbol, node ID, cases, mock constraints, and uncovered line targets.
2. **Resilient Tiered LLM Router (`src/testpulse/llm/router.py`)**:
   - Sequential model failover reading `settings.tier1_models` (`TESTPULSE_TIER1_MODELS` in `.env`).
   - Automatically catches HTTP 429 (`RateLimitError`), 503 (`ServiceUnavailableError`), and timeouts, logs warnings, waits 2.0 seconds, and seamlessly fails over to the next candidate model in the tier.
   - Structured Pydantic parsing with code-fence cleanup (`clean_json_code_fences`) stripping markdown ```json ... ``` blocks and extracting raw JSON from conversational wrapper text.
   - OpenRouter provider prefix normalization preventing `BadRequestError`.
3. **Multi-Strategy Context Gathering Agent (`src/testpulse/pipeline/context_gatherer.py`)**:
   - **Target Prioritization (`select_targets`)**:
     * Unit Strategy: Bottom-up selection of non-trivial business logic via `select_unit_targets(G)`, strictly filtering out trivial getters/setters (`cyclomatic_complexity <= 1` and `< 6` lines).
     * Integration Strategy: Top-down selection of FastAPI route entry points via `select_integration_targets(G)` sorted by downstream multi-hop dependencies.
     * Regression Strategy: Computes 2-hop blast radius ($ModifiedNodes \cup Callers^2 \cup Dependencies^1$) via `compute_blast_radius(G, modified_nodes)`, requiring explicit `modified_nodes`.
   - **Context Bundle Assembly (`build_bundle`)**:
     * Adapts hop depth dynamically (1 for unit, 2 for integration, 2 for regression).
     * Uses `retrieve_context_artifacts` to separate focal code from Pipeline A graph walk chunks and Pipeline B semantic document chunks (e.g. `README.md` 50% discount cap).
     * Formulates strategy-specific mock boundaries:
       - Unit: Isolates target in memory; mocks external I/O; strictly forbids mocking the target symbol or its internal logic.
       - Integration: Exercises full FastAPI `TestClient` $\to$ Service $\to$ SQLite flow; forbids mocking internal services or the database; only permits mocking external 3rd-party APIs.
       - Regression: Inherits unit or integration isolation depending on entry point status and enforces mandatory Fail-to-Pass (F2P) defect reproduction.
     * Discovers existing pytest fixtures from `conftest.py` files using AST traversal.
4. **Test Planning Agent (`src/testpulse/pipeline/planner.py`)**:
   - Synthesizes exhaustive, strategy-aware `BehaviorMatrix` plans via Tier-1 LLM Router acting as the "TestPulse QA Architect".
   - Unit system prompt demands complete branch coverage, strict mathematical/business boundaries, and negative error-raising paths.
   - Integration prompt demands HTTP status codes (200/201, 404, 422), schema validation edge cases, and SQLite database state verification.
   - Regression prompt demands a mandatory Fail-to-Pass reproducer case targeting modified logic plus caller contract preservation cases.
   - Declared `__test__ = False` preventing Pytest collection warnings.
5. **Sequential Single-Sandbox Execution Constraint**:
   - All targets and agent executions remain strictly sequential (zero concurrent threads or async loops) respecting the 16GB RAM ceiling, single Docker sandbox constraint, and OpenRouter free-tier rate limits.

### Deliverables Created & Modified
- **Data Contracts**:
  - `src/testpulse/models/schemas.py`: Defined `StrategyType`, `ContextBundle`, `BehaviorCase`, and updated `BehaviorMatrix`.
  - `src/testpulse/models/__init__.py`: Exported new schemas.
- **RAG Subsystem**:
  - `src/testpulse/rag/retriever.py`: Added `retrieve_context_artifacts` returning cleanly separated focal, dependency, and descriptive chunks; refactored `get_context_for_target`.
  - `src/testpulse/rag/__init__.py`: Exported `retrieve_context_artifacts`.
- **LLM Gateway**:
  - `src/testpulse/llm/__init__.py`: Package root.
  - `src/testpulse/llm/router.py`: Resilient tiered LLM router with failover on 429/503/timeout and markdown fence cleanup.
- **Pipeline Subsystem (`src/testpulse/pipeline/`)**:
  - `src/testpulse/pipeline/__init__.py`: Package root exporting `ContextGatherer` and `TestPlanner`.
  - `src/testpulse/pipeline/context_gatherer.py`: Target prioritization, conftest fixture discovery, and separated bundle assembly.
  - `src/testpulse/pipeline/planner.py`: Strategy-aware test planning agent producing `BehaviorMatrix`.
- **Automated Tests (`tests/unit/test_pipeline_m3.py`)**:
  - 15 comprehensive unit tests verifying target queue selection across 3 strategies, clean context separation in bundles (including README discount rule), LLM router failover on 429/503/timeout, fence stripping, and valid BehaviorMatrix generation for unit, integration, and regression.

### Verification Output
- **Ruff Linter**:
  ```
  .\.venv\Scripts\ruff.exe check .
  All checks passed!
  ```
- **Pyright Static Type Checker**:
  ```
  .\.venv\Scripts\pyright.exe src/ tests/
  0 errors, 0 warnings, 0 informations
  ```
- **Automated Test Suite**:
  ```
  .\.venv\Scripts\pytest.exe tests/ -v
  39 passed in 7.13s (100% green)
  ```
- **Constitution Compliance**:
  - Client repository remained read-only and inviolable.
  - Component 1 remained backend-only (FastAPI/SQLite/Python; zero frontend React mocks).
  - Anti-shallow discipline upheld (zero assertions rejected, strict boundaries, F2P requirement).
  - Sequential single-target processing constraint maintained.

### Limitations & Next Steps
- Planner currently produces high-precision structured behavior matrices; test code synthesis in python files is handled by the Writer agent.
- Next target: **Milestone 4 — Greenfield Test Synthesis (Writer Agent) & Ephemeral Docker Sandbox Execution with Write Safety**.

---

## [Milestone 4] Greenfield Test Synthesis (Writer Agent) & Dual-Phase Validator (Component 1)

**Date**: 2026-10-23
**Status**: COMPLETE (Verified)

### Goals
Implement the final two agents of the sequential 4-agent state machine alongside the main pipeline orchestrator:
1. **Writer Agent (`src/testpulse/pipeline/writer.py`)**: Consumes `ContextBundle` and `BehaviorMatrix` to synthesize clean, PEP-8 compliant, anti-shallow pytest test suites adhering to strategy mocking boundaries.
2. **Dual-Phase Validator Agent (`src/testpulse/pipeline/validator.py`)**:
   - **Phase 1 (Internal Static AST)**: Tree-sitter AST visitor detecting and immediately rejecting missing assertions, tautologies (`assert True`, `assert x is not None`, `assert 1 == 1`), conditional assertions (inside `if`/loop blocks), and swallowed exceptions (`try...except: pass`).
   - **Phase 2 (External Dynamic)**: Ephemeral Docker/SQLite sandbox execution, coverage ratchet, and strategy-specific dynamic gates (Unit targeted mutation testing, Integration 3-run flakiness check, Regression Fail-to-Pass check).
3. **Pipeline Orchestrator (`src/testpulse/pipeline/orchestrator.py`)**: Orchestrates the sequential `ContextGatherer` -> `TestPlanner` -> `TestWriter` -> `Validator` flow with internal loop-back (to Planner) and external loop-back (to Writer) bounded to 3 retries.
4. **Comprehensive Mocked Unit Tests (`tests/unit/test_pipeline_m4.py`)**: Fast, hermetic verification with zero Docker or network latency.

### Key Accomplishments
1. **Schema Contracts (`src/testpulse/models/schemas.py`)**:
   - Added `CandidateTest`: `test_code`, `fixtures_needed`, `test_file_name`.
   - Added `ValidationResult`: `is_valid`, `failed_phase` (`"internal" | "external" | "none"`), `feedback`, `coverage_achieved`, `exit_code`, `stderr`, `mutants_killed`, `mutants_survived`.
2. **The Writer Agent (`src/testpulse/pipeline/writer.py`)**:
   - Implemented `TestWriter.synthesize(bundle, matrix, feedback)` consuming the BehaviorMatrix and ContextBundle.
   - Strategy-specific prompting:
     * Unit: Direct invocation of target symbol, `unittest.mock.patch` exclusively for external I/O, strictly forbids mocking the target function/logic.
     * Integration: Uses FastAPI `TestClient` / `pytest.mark.asyncio`, exercises real SQLite database state, forbids mocking database or internal service providers.
     * Regression: Targets blast radius boundaries and implements the mandatory Fail-to-Pass reproducer.
   - Robust markdown fence stripping (`extract_python_code`) and automated fixture discovery from AST test signatures (`extract_fixtures_needed`).
   - Added `__test__ = False` to prevent pytest collection warnings.
3. **Dual-Phase Validator Agent (`src/testpulse/pipeline/validator.py`)**:
   - **Phase 1 Internal Static AST Smell Detection (`detect_ast_smells`, `run_internal_validation`)**:
     * Zero Assertions: Traverses all `test_*` functions; flags functions with zero assertions or `pytest.raises` checks.
     * Tautological Assertions: Detects `assert True`, `assert False`, shallow existence checks (`assert x is not None`, `assert x != None`), constant literals, and identical operand comparisons (`assert 1 == 1`).
     * Conditional Assertions: Identifies assertions nested within `if_statement`, `for_statement`, or `while_statement` ancestor nodes.
     * Swallowed Exceptions: Flags `try...except` blocks containing only `pass` or `...` statements, recommending `with pytest.raises(...)`.
     * Immediately returns `is_valid=False`, `failed_phase="internal"` with detailed actionable feedback.
   - **Phase 2 External Dynamic Validation (`run_external_validation`, `default_sandbox_runner`)**:
     * Sandboxed compilation & test execution; reports Problem A compilation errors if `exit_code != 0`.
     * Unit Strategy (Targeted Mutation): Syntactically inverts logic operators (`<` to `>=`, `>` to `<=`, `==` to `!=`, `+` to `-`) using `ast.NodeTransformer` (`LogicMutator`). Rejects tests where mutants survive (`mutants_survived > 0`) as shallow/weak.
     * Integration Strategy (Flakiness Check): Executes test suite 3 times in randomized order to detect database state leakage, uncleared tables, or teardown failures across runs.
     * Regression Strategy (Fail-to-Pass Check): Tests against pre-fix snapshot $T_0$ (must fail to reproduce bug) and post-fix snapshot $T_1$ (must pass to verify fix).
     * Accepts pluggable/mockable `runner_fn` for instantaneous, deterministic unit testing.
4. **Pipeline Orchestrator (`src/testpulse/pipeline/orchestrator.py`)**:
   - Sequentially connects all 4 agents (`ContextGatherer` -> `TestPlanner` -> `TestWriter` -> `Validator`).
   - **Internal Loop-Back**: Rejection by Phase 1 AST smell check loops back to `TestPlanner.generate_plan` with `feedback=val_internal.feedback`, instructing the Planner to synthesize a more rigorous BehaviorMatrix (increments `internal_retries`).
   - **External Loop-Back**: Rejection by Phase 2 dynamic gates loops back to `TestWriter.synthesize` with `feedback=val_external.feedback` (stderr/traceback) to correct syntax, imports, or mocking issues (increments `external_retries`).
   - Enforces strict retry cap (`max_retries = 3`). Returns `status="accepted"` on success or `status="rejected"` when retries are exhausted.
5. **Unit Verification Suite (`tests/unit/test_pipeline_m4.py`)**:
   - 21 thorough unit tests verifying all Phase 1 AST smell rejections, clean assertion acceptance, Phase 2 dynamic gates (mutation kill/survival, integration 3-run flakiness, regression T0/T1 F2P), writer synthesis, and orchestrator loop-backs.
   - Completely mocked LLM completions and sandbox runner execution for fast, hermetic test execution.

### Deliverables Created & Modified
- **Data Contracts**:
  - `src/testpulse/models/schemas.py`: Added `CandidateTest` and `ValidationResult`.
- **Pipeline Subsystem (`src/testpulse/pipeline/`)**:
  - `src/testpulse/pipeline/__init__.py`: Exported `ContextGatherer`, `TestPlanner`, `TestWriter`, `Validator`, `PipelineOrchestrator`, `run_pipeline`.
  - `src/testpulse/pipeline/writer.py`: Greenfield pytest synthesis agent.
  - `src/testpulse/pipeline/validator.py`: Dual-phase validator (Tree-sitter AST smell detector + Dynamic Sandbox Gates).
  - `src/testpulse/pipeline/orchestrator.py`: Sequential pipeline orchestrator managing feedback loops and bounded retries.
  - `src/testpulse/pipeline/planner.py`: Added feedback injection into user prompt for internal loop-back.
- **Automated Tests (`tests/unit/test_pipeline_m4.py`)**:
  - 21 unit tests covering all Milestone 4 capabilities.

### Verification Output
- **Ruff Linter**:
  ```
  .\.venv\Scripts\ruff.exe check .
  All checks passed!
  ```
- **Pyright Static Type Checker**:
  ```
  .\.venv\Scripts\pyright.exe src/ tests/
  0 errors, 0 warnings, 0 informations
  ```
- **Automated Test Suite**:
  ```
  .\.venv\Scripts\pytest.exe tests/ -v
  60 passed in 21.54s (100% green)
  ```
- **Constitution Compliance**:
  - Client repository remained inviolable and read-only.
  - Component 1 remained backend-only (Python/FastAPI/SQLite).
  - Anti-shallow validation discipline strictly enforced (Tree-sitter AST smell checks + targeted mutation + flakiness + F2P).
  - Problem A vs. Problem B separation adhered to (compilation/runner errors routed cleanly via `failed_phase="external"`).
  - Sequential single-target processing constraint maintained.

### Limitations & Next Steps
- Milestone 4 delivers the complete 4-agent sequential pipeline (Gatherer -> Planner -> Writer -> Validator) with automated feedback loops and verified dynamic gates.
- Next target: **Milestone 5 — Ephemeral Docker Sandbox Execution & Full Component 1 Integration**.




