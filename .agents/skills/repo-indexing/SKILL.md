---
name: repo-indexing
description: Guidelines and patterns for ingesting client repositories, building structural AST knowledge graphs (Tree-sitter + NetworkX, adapted locally from Graphify-Labs/graphify), and constructing the Qdrant Local code-aware RAG index.
---

# Skill: Repo Indexing & Graph Ingestion

## Purpose
Guide the indexing of client application codebases. This skill coordinates multi-language Tree-sitter parsing, NetworkX structural knowledge graph generation (vendored and adapted locally from the official Graphify repository at `https://github.com/Graphify-Labs/graphify`), AST hashing for rolling diffs, and Qdrant Local vector index construction using remote API embeddings.

## Key Principles
1. **Client Read-Only Inviolability**: Never write, create, or modify files within the target client repository.
2. **Local Graphify Adaptation**: Use the adapted in-house components in `src/testpulse/graph/` (adapted locally from `https://github.com/Graphify-Labs/graphify`). Do not call external graph APIs.
3. **Lazy Qdrant Open/Close**: Open `QdrantClient(path=".testpulse/qdrant")` strictly within the RAG indexing scope; close it immediately once vectors are flushed.
4. **Remote API Embeddings**: Use the remote embedding model configured via `TESTPULSE_EMBEDDING_MODEL` to preserve host RAM.

## Workflow Steps
1. **File Scanning & Filtering**:
   - Traverse workspace respecting `.gitignore` and skipping virtualenvs (`.venv`, `node_modules`).
   - Identify backend Python modules (FastAPI entry points, routers, models, services) and frontend JS/TS files (for cross-layer route references).
2. **AST Parsing**:
   - Parse files using Tree-sitter grammars.
   - Extract symbols (functions, classes, methods, endpoints) and compute AST body SHA-256 hashes.
3. **Graph Construction**:
   - Populate NetworkX directed graph with nodes (files, classes, functions, routes) and edges (calls, imports, inherits, defines).
   - Identify central entry points and calculate 2-hop blast radius topologies.
4. **RAG Vector Storage**:
   - Chunk code by semantic AST boundaries.
   - Embed chunks using remote API in batches.
   - Insert points into Qdrant Local collection and close client.
