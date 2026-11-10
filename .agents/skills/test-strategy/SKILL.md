---
name: test-strategy
description: Formulating behavior matrices, coverage ratchets, and test planning profiles (unit, integration, regression) for target codebases.
---

# Skill: Test Strategy & Planning

## Purpose
Guide the synthesis of validated test plans and behavior matrices across different testing phases (Unit, Integration, Regression) without shallow checks or mock abuse.

## Strategy Profiles

### 1. Unit Testing Strategy Profile (Backend Scope)
- Target individual functions, business rules, calculations, and domain validators.
- Strict isolation: mock external I/O (network, third-party APIs), but **never mock the target class/function itself**.
- Behavior Matrix covers:
  * Happy path (nominal inputs, standard state transitions).
  * Boundary conditions (empty lists, 0, None, max limits, off-by-one bounds).
  * Error cases (validation errors, domain exceptions, edge constraints).

### 2. Integration Testing Strategy Profile
- Target real FastAPI endpoints (`@app.get`, `@app.post`, `@router.put`).
- Use real in-sandbox SQLite database redirected to `/tmp/test_sqlite.db`.
- Exercise full route $\to$ service $\to$ database transaction flows using `httpx.AsyncClient` or `TestClient`.
- Verify database state changes (e.g., verifying row insertion in DB after POST).

### 3. Regression Testing Strategy Profile
- Target modified symbols and their 2-hop graph blast radius derived from AST body hash diffs.
- Require strict **Fail-to-Pass (F2P)** verification:
  * Generated test must actively fail on the pre-fix snapshot (confirming reproduction).
  * Generated test must pass on the post-fix snapshot (confirming resolution).

## Provenance Tracking
Tag each planned behavior with its evidentiary basis:
- `code_evidence`: Direct logic branching observed in AST.
- `doc_evidence`: Docstrings or type annotations.
- `test_evidence`: Pre-existing behavioral clues from client tests (read-only).
- `inferred`: Logical deduction; must not be claimed as ground truth.
