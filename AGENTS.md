# TestPulse — Project Constitution (AGENTS.md)

> This file is read by every AI coding agent (Antigravity 2.0, Claude Code, etc.) before
> performing any task inside this repository. It is the single authoritative contract.
> Non-negotiable constraints are marked **[INVIOLABLE]**.

---

## 1. Fundamental Purpose

TestPulse is an **autonomous agentic QA and verification platform**. It sits alongside
an external AI coding agent (Antigravity 2.0) and is invoked via MCP over stdio.
TestPulse ingests application codebases, builds structural AST knowledge graphs, and
generates, executes, and validates fresh tests inside ephemeral Docker sandboxes. When
code defects or browser crashes occur, it returns structured, evidence-backed findings
to the coding agent to drive targeted repairs.

---

## 2. Inviolable Laws

**[INVIOLABLE] 1. Client Repository Inviolability**
TestPulse NEVER writes to, modifies, or deletes files in the client's repository source
tree. All generated test files, snapshots, and execution logs reside exclusively inside
TestPulse's internal directories (`.testpulse/`, `runs/`).

**[INVIOLABLE] 2. Component 1 Backend Scope Only**
Component 1 is strictly scoped to backend APIs, business logic, and database interactions
(anchored to Python/FastAPI/SQLite for Phase 1). It MUST NEVER attempt to unit-test React
or Next.js frontend components or write JSDOM mocks. All frontend validations belong
strictly to Component 2 (Playwright E2E). Multi-language support (Node.js, PostgreSQL) is
deferred behind a `BaseLanguageAdapter` interface and must NOT be implemented until the
FastAPI baseline is fully operational and reviewed.

**[INVIOLABLE] 3. Fresh Test Generation**
TestPulse generates greenfield test suites from scratch. It never relies on pre-existing
tests or existing test coverage in the client repository. If client tests exist, they may
be read as secondary behavioral evidence during planning, but are never modified and never
used to measure baseline coverage.

**[INVIOLABLE] 4. Anti-Shallow Validation Discipline**
Every generated test MUST pass the rigorous multi-stage verification pipeline before being accepted:
- **Gate 1 (Static AST Test-Smell Detection)**: Scans generated test code using Tree-sitter before execution. Immediately rejects:
  * Zero assertions (no `assert` statement)
  * Trivial tautologies (e.g. `assert response is not None`, `assert result is not None`, `assert True`)
  * Conditional assertions (assertions nested inside `if` statements or loops)
  * Mock abuse (where the actual method/class under test or forbidden internal services are mocked instead of exercised)
- **Sandbox Execution & Coverage Ratchet**: Runs in an ephemeral Docker sandbox. Verifies the test compiles, executes cleanly (`exit_code == 0`), and strictly exercises the targeted lines and branch conditions outlined in the Planner's Behavior Matrix.
- **Exit Code Routing (Problem A vs. Problem B Triage)**:
  * If `exit_code != 0`: Skip Gate 2 mutation completely and route directly to Problem A (test fault repair loop, max 3 retries) vs. Problem B (app defect finding report).
  * If `exit_code == 0`: Proceed to Gate 2 Targeted Mutation.
- **Gate 2 (Targeted Mutation Testing — Proof of Test Quality)**: Injects 2–3 targeted logic mutations (e.g., flipping `<` to `>=`, `+` to `-`, boolean inversion) into a temporary sandbox copy of covered code.
  * Mutants killed $\to$ test verified as high-strength and accepted.
  * Mutants survived $\to$ test rejected as shallow/weak and routed back to Writer.
- **Flakiness & Fail-to-Pass (F2P) Checks**: Integration tests run multiple times in randomized order to catch state leaks. Regression tests must actively fail on the old buggy code snapshot and pass on the newly fixed code.

**[INVIOLABLE] 5. Problem A vs. Problem B Separation**
Internal test-quality failures (Problem A) and application defects (Problem B) are
distinct concerns with distinct handling. A failing test is NEVER reported as an
application bug unless it has passed structural validity checks and provides verifiable
execution traces.

**[INVIOLABLE] 6. Host-Native Execution on Windows 11**
TestPulse's FastAPI backend, LangGraph orchestrator, and MCP server execute natively
in the host Python `.venv`. Docker is used exclusively for:
1. Ephemeral test runner containers (`Dockerfile.sandbox-python`)
2. Ephemeral live application stacks for Component 2 Playwright browser testing
Do NOT containerize the TestPulse engine itself.

**[INVIOLABLE] 7. Hardware Discipline & Sandbox Reliability**
- Use local SQLite (`.testpulse/testpulse.db`) and Qdrant Local Mode. NEVER spin up
  long-running PostgreSQL or Qdrant Docker containers.
- Enable `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` on all SQLite
  connections (concurrent access from FastAPI and MCP servers).
- Open `QdrantClient(path=".testpulse/qdrant")` lazily per RAG call only; close
  immediately after. Never open at FastAPI startup.
- Use remote API embeddings ONLY (zero host RAM for PyTorch/transformers).
- Ephemeral test sandboxes default to a 2GB RAM cap via `TESTPULSE_SANDBOX_MEMORY_LIMIT`,
  but this limit is configurable and expandable as needed to ensure client applications
  execute reliably without OOM crashes. Destroy ephemeral containers immediately after runs.

**[INVIOLABLE] 8. Uncompromised Test Quality & Model Tiering**
- Load model slugs from `.env` via `TESTPULSE_TIER1_MODELS` and `TESTPULSE_TIER2_MODELS`.
  Never hardcode model slugs in source code or this file.
- Test quality, thoroughness, and repair loops must NEVER be degraded or truncated to save
  tokens; paid subscriptions will be used when needed to ensure full QA depth.
- Default `max_targets` to 5 per phase for focused evaluation.
- Enforce bounded repair loops: max 3 retries per test target.
- Run deterministic Tree-sitter AST linting and smell checks before spending any LLM call on repair.

**[INVIOLABLE] 9. Sandbox Write Safety**
Inside the ephemeral `--rm --network=none` test sandbox:
- Client repository snapshot is mounted read-only (`:ro`).
- Client FastAPI app's SQLite database is redirected to `/tmp/test_sqlite.db` via
  environment variable injection (`TESTPULSE_SANDBOX_DB_PATH=/tmp/test_sqlite.db`).
- `PYTHONDONTWRITEBYTECODE=1` is always set in the sandbox environment.

**[INVIOLABLE] 10. Pre-Baked Sandbox Dependencies**
The `Dockerfile.sandbox-python` MUST pre-install the full target FastAPI stack
(fastapi, pydantic, pydantic-settings, sqlalchemy, aiosqlite, sqlmodel, pytest,
pytest-cov, pytest-asyncio, httpx) so that client apps never fail with
`ModuleNotFoundError` when sandboxes run with `--network=none`.

---

## 3. Architecture Overview

```
TestPulse Platform (Native .venv on Windows 11 Host)
├── MCP Server (stdio) ←→ Antigravity 2.0
├── FastAPI Backend (REST + Dashboard API)
├── LangGraph Orchestrator (State Machine)
├── Native AST Engine (Tree-sitter + NetworkX, adapted locally from Graphify)
├── Code-Aware RAG (Qdrant Local + Remote API Embeddings)
└── Component 1: Test Generation Pipeline
    ├── Context Gatherer (Graph + RAG)
    ├── Planner (Behavior Matrix via Tier1 LLM)
    ├── Writer (Greenfield Test Synthesis)
    ├── Ephemeral Docker Sandbox (Isolated Execution)
    └── Validator (AST Smells → exit_code → Mutation → Triage)

Ephemeral Docker Containers (On-Demand Only)
├── Dockerfile.sandbox-python (Component 1 test execution)
└── App stack containers (Component 2 browser testing)
```

**Component Phases:**
- **Phase 1 (Component 1)**: Code-Level Testing — Python/FastAPI/SQLite only.
- **Phase 2 (Component 2)**: Playwright Browser Testing.
- **Phase 3 (Component 3)**: Cross-Layer Root-Cause Analysis (RCA).

---

## 4. Technology Stack

- **Host Runtime**: Python 3.11+ in `.venv` on Windows 11
- **Backend API**: FastAPI with uvicorn[standard]
- **Orchestration**: LangGraph (StateGraph)
- **Metadata DB**: SQLite via SQLAlchemy 2.0 async + aiosqlite (WAL mode)
- **Vector Store**: Qdrant Local Mode (lazy open/close per RAG call)
- **Embeddings**: Remote API (configured via TESTPULSE_EMBEDDING_MODEL)
- **AST Engine**: Tree-sitter + NetworkX (cloned and adapted locally from Graphify-Labs/graphify; zero external API calls)
- **LLM Gateway**: litellm via OpenRouter (configurable model routing, uncompromised test quality)
- **Test Sandboxes**: Docker (python:3.11-slim, pre-baked deps, configurable memory cap via `TESTPULSE_SANDBOX_MEMORY_LIMIT`)
- **Anti-Shallow**: AST Smell Visitor (Gate 1) + Coverage Ratchet + exit_code Router + Targeted Mutator (Gate 2) + F2P Checks
- **Dashboard**: React + Vite (local only, no auth)

---

## 5. Development Workflow (per milestone)

1. Read this file and `.agents/rules/RULES.md` before starting any work.
2. Check `IMPLEMENTATION_LOG.md` for the current milestone target and state.
3. Implement **only** the requested milestone scope. Do not implement features ahead of schedule.
4. Run `ruff check .` and `pytest tests/` — both must pass before claiming completion.
5. Update `IMPLEMENTATION_LOG.md` with goal, files changed, verification output, and limitations.
6. Stop and wait for explicit instruction before proceeding to the next milestone.

---

## 6. Key References

| Document | Purpose |
|---|---|
| `docs/architecture.md` | Full architecture plan (trimmed version) |
| `.agents/rules/RULES.md` | Detailed engineering rules |
| `.agents/skills/repo-indexing/SKILL.md` | Repo ingestion workflow |
| `.agents/skills/test-strategy/SKILL.md` | Strategy profile authoring |
| `.agents/skills/sandbox-execution/SKILL.md` | Ephemeral Docker sandbox guide |
| `.agents/skills/milestone-completion/SKILL.md` | Milestone sign-off workflow |
| `IMPLEMENTATION_LOG.md` | Current milestone progress |
