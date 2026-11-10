# RULES.md — TestPulse Engineering Rules

> Read this file alongside `AGENTS.md` before performing any engineering task.
> These rules codify patterns that must be applied consistently across all modules.

---

## 1. Module Boundaries

- Business logic resides strictly in `core/`, `graph/`, `rag/`, `pipeline/`,
  `browser/`, and `rca/`.
- The `mcp/` module is a **thin adapter layer** that forwards requests to `core/` and
  formats structured responses. No business logic belongs in `mcp/`.
- The `api/` module contains FastAPI route handlers only. All logic is delegated to
  service modules.
- Modules communicate exclusively via validated **Pydantic v2 models** from
  `models/schemas.py`. Do NOT pass untyped dictionaries across module boundaries.

---

## 2. Python Code Standards

- Python 3.11+ strict type annotations on **all** public functions, methods, and classes.
- Formatted and linted using `ruff`. Run `ruff check .` before committing.
- No raw SQL queries. Use SQLAlchemy 2.0 async ORM (`AsyncSession`, `select()`).
- Structured logging using `structlog` with JSON output. Every log record inside a
  pipeline execution must include `run_id` in its context.
- No `Any` types in public API boundaries. Use `object` or proper union types.

---

## 3. SQLite Configuration (WAL Mode)

All SQLAlchemy engine creation for `.testpulse/testpulse.db` MUST apply WAL mode:

```python
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import event

engine = create_async_engine(
    "sqlite+aiosqlite:///.testpulse/testpulse.db",
    echo=False,
)

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()
```

This ensures concurrent access from the FastAPI server and MCP stdio server does
not produce `database is locked` errors.

---

## 4. Qdrant Lazy Open/Close Pattern

The `QdrantClient` for local mode MUST be opened and closed per operation:

```python
from qdrant_client import QdrantClient

def get_qdrant() -> QdrantClient:
    """Open a new local Qdrant client. Always close after use."""
    return QdrantClient(path=".testpulse/qdrant")

# Usage:
client = get_qdrant()
try:
    results = client.search(...)
finally:
    client.close()
```

**Never** open a `QdrantClient` at FastAPI application startup or as a global singleton.
This prevents file-lock collisions between the API process and background workers.

---

## 5. Sandbox Execution Rules

Every ephemeral test sandbox container is launched with configurable resource limits (default 2GB, expandable via `TESTPULSE_SANDBOX_MEMORY_LIMIT`):

```
--memory="${TESTPULSE_SANDBOX_MEMORY_LIMIT:-2048m}"
--memory-swap="${TESTPULSE_SANDBOX_MEMORY_LIMIT:-2048m}"
--cpus="2.0"
--network="none"
--rm
```

**Read-only client code mount:**
```
-v /path/to/snapshot:/workspace:ro
```

**Writable test artifacts mount:**
```
-v /path/to/generated_tests:/tests:rw
```

**Required environment variables inside sandbox:**
```
PYTHONDONTWRITEBYTECODE=1
TESTPULSE_SANDBOX_DB_PATH=/tmp/test_sqlite.db
```

This prevents `sqlite3.OperationalError: attempt to write a readonly database` when the
client FastAPI application attempts to create/write its SQLite database during integration
tests.

**Execution timeout**: 30 seconds hard limit. Kill the container if it exceeds this.

---

## 6. LLM Routing & Quality Standards

- All LLM calls route through `llm/router.py`. Never call `litellm.completion()`
  directly from pipeline modules.
- Model lists are configured in `.env` (`TESTPULSE_TIER1_MODELS`, `TESTPULSE_TIER2_MODELS`).
- Test generation depth and validation thoroughness must NEVER be degraded or truncated
  for artificial token thrift. Paid OpenRouter tiers are supported and prioritized for QA quality.
- Handle HTTP 429 (Rate Limit) gracefully: catch the exception, apply exponential
  backoff (1s, 2s, 4s), and automatically rotate to the next model in the configured list.
- All structured LLM outputs MUST be parsed and validated using Pydantic models.
  Never forward raw LLM string output to other modules.
- Maximum LLM repair attempts per test target: 3 retries. Always run deterministic Tree-sitter
  smell and syntax checks before calling the LLM repair loop.

---

## 7. Error Handling

- Never swallow exceptions silently. All exceptions must be logged with `structlog.error()`.
- LLM failures → retry with exponential backoff (max 3 attempts) → if all fail, mark
  the test target as `inconclusive` and report.
- Sandbox failures → capture stdout/stderr → triage → report.
- Failed pipeline stages transition the run record to `failed` status with a descriptive
  error message stored in the database.

---

## 8. Evidence & Provenance Standards

- Every `FINDING` record must reference: source file, line range, the specific generated
  test that revealed it, and the behavioral expectation that was violated.
- The `Planner` must tag each behavior in the behavior matrix as one of:
  `code_evidence`, `doc_evidence`, `test_evidence`, or `inferred`. Never present
  `inferred` behaviors as verified facts.

---

## 9. Generated Artifacts

All generated artifacts go under `.testpulse/runs/{run_id}/`:

```
.testpulse/runs/{run_id}/
├── generated_tests/   # Generated pytest files
├── coverage/          # Cobertura XML reports
├── mutation/          # Mutated source copies and results
└── reports/           # Final structured reports
```

Generated artifacts MUST NEVER be written into the client's source tree.

---

## 10. Anti-Shallow Validation Protocol (`pipeline/validator.py`)

All generated tests must undergo the strict 4-stage validation discipline:
1. **Gate 1 (Static AST Test-Smell Detection)**: Scans generated test with Tree-sitter before execution.
   - Reject zero assertions.
   - Reject trivial tautologies (`assert x is not None`, `assert True`).
   - Reject conditional assertions wrapped in `if` statements or loops.
   - Reject mock abuse (mocking the target function, target class, or forbidden internal services).
2. **Sandbox Execution & Coverage Ratchet**:
   - Verify execution compiles and passes (`exit_code == 0`).
   - Verify coverage ratchet: target lines specified in the Planner's Behavior Matrix must be executed.
3. **Exit Code Routing**:
   - If `exit_code != 0`: Skip mutation entirely. Route to Problem A (test repair loop, max 3 retries) vs. Problem B (app defect finding).
   - If `exit_code == 0`: Route to Gate 2 Targeted Mutation.
4. **Gate 2 (Targeted Mutation Testing)**:
   - Inject 2–3 logic mutations in covered lines of a sandbox copy.
   - Re-run test: Mutants must be killed (test must fail). If mutants survive, test is rejected as weak/shallow.
5. **Flakiness & Fail-to-Pass Checks**:
   - Integration tests: Run multiple times in randomized order.
   - Regression tests: Must actively fail on old buggy code snapshot and pass on new fixed code.

---

## 11. Graphify Local Integration Pattern (`src/testpulse/graph/`)

- Clone the **Graphify** repository (`https://github.com/Graphify-Labs/graphify`) and vendor/adapt the required AST extraction and graph building modules directly inside `src/testpulse/graph/`.
- Do NOT use Graphify as an external API or remote service.
- Adapt and modify the code specifically for TestPulse (Python FastAPI/SQLite and JS/TS route parsing).
- Exclude and skip unneeded parts of the upstream repository (e.g., multimodal audio/video/PDF pipelines) to keep dependencies lean and execution fast.

---

## 12. Verification Protocol (Every Milestone)

Before declaring any milestone complete:

1. `ruff check .` — must return zero errors.
2. `pyright src/ tests/` — must return zero errors (zero red IDE / Pylance type diagnostics).
3. `pytest tests/` — all tests must pass.
4. Manual verification command provided in `IMPLEMENTATION_LOG.md`.
5. `IMPLEMENTATION_LOG.md` updated with:
   - Milestone ID and goal
   - Key files created and modified
   - Verification output (copy-pasted or described)
   - Known limitations and open items
6. Stop and await explicit instruction before proceeding.

