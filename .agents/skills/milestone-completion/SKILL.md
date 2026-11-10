---
name: milestone-completion
description: Verification protocol and sign-off workflow required before claiming completion of any milestone in TestPulse.
---

# Skill: Milestone Completion & Sign-Off Workflow

## Purpose
Enforces discipline and rigor across all milestone deliverables. No milestone may be claimed as complete without satisfying all verification gates.

## Pre-Sign-Off Checklist
1. **Scope Adherence**: Only files and features within the current milestone's planned scope were touched or implemented. No feature creep into future milestones.
2. **Linting & Code Quality**:
   ```bash
   ruff check .
   ```
   Must return zero errors and zero warnings.
3. **Static Type Checking (Pyright / Pylance)**:
   ```bash
   pyright src/ tests/
   ```
   Must return zero errors and zero red IDE type diagnostics across the workspace.
4. **Automated Test Suite**:
   ```bash
   pytest tests/
   ```
   All existing and newly added unit/integration tests must pass with 100% green exit code.
5. **Constitution Compliance**:
   - Client repository remained inviolable (read-only).
   - Component 1 remained backend-only (no frontend React unit mocks).
   - SQLite WAL mode applied on all database connections.
   - Qdrant Local client opened/closed lazily per call.
   - Anti-shallow validation rules upheld.
6. **Update IMPLEMENTATION_LOG.md**:
   Record:
   - Milestone ID and title
   - Summary of changes and delivered components
   - Key files created and modified
   - Verification command outputs
   - Known limitations and deferred items
7. **Stop & Await Instruction**:
   Present milestone summary clearly and wait for user review before starting the next milestone.
