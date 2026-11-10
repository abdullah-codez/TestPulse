---
name: sandbox-execution
description: Standard operating procedure for executing generated test suites inside ephemeral, resource-capped Docker sandbox containers.
---

# Skill: Sandbox Execution Guide

## Purpose
Direct safe, isolated, and deterministic test execution inside ephemeral Docker containers without risking host compromise or read-only filesystem errors.

## Mandatory Docker Flags
All sandbox test executions must use:
```bash
docker run --rm \
  --network="none" \
  --memory="${TESTPULSE_SANDBOX_MEMORY_LIMIT:-2048m}" \
  --memory-swap="${TESTPULSE_SANDBOX_MEMORY_LIMIT:-2048m}" \
  --cpus="2.0" \
  -v "${CLIENT_SNAPSHOT_DIR}:/workspace:ro" \
  -v "${RUN_TESTS_DIR}:/tests:rw" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e TESTPULSE_SANDBOX_DB_PATH=/tmp/test_sqlite.db \
  testpulse/sandbox-python:latest \
  pytest /tests/ -v --cov=/workspace --cov-report=xml:/tests/coverage.xml
```

## Critical Guardrails
1. **Network Disabled**: `--network="none"` ensures hermetic execution. All dependencies must be pre-baked in `Dockerfile.sandbox-python`.
2. **Read-Only Client Snapshot**: Mounted `:ro`. Client code cannot be contaminated or modified.
3. **SQLite Redirection**: `TESTPULSE_SANDBOX_DB_PATH=/tmp/test_sqlite.db` redirects client SQLite creation to writable `/tmp`, avoiding `sqlite3.OperationalError: attempt to write a readonly database`.
4. **Execution Timeout**: Enforce a strict 30-second execution timeout. If a process hangs or enters an infinite loop, terminate and collect stderr.
5. **Exit Code Routing**:
   - `exit_code == 0`: Test passed on original code $\to$ Proceed to Gate 2 Targeted Mutation.
   - `exit_code != 0`: Test failed on original code $\to$ Skip mutation and route to Problem A / Problem B triage.
