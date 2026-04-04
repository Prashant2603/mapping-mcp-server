# MCP RAG Server

A RAG-powered MCP server that lets LLMs (via Copilot Studio or any MCP client) search and reason over mapping sets, format definitions, and function docs using natural language.

**No LLM is used internally.** The server is pure retrieval — it embeds queries with sentence-transformers, performs cosine similarity search in ChromaDB, and returns raw chunks/files. All reasoning happens in the external LLM client (e.g. Copilot Studio) that calls the tools. No LangChain or similar orchestration frameworks are used.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.12 |
| **MCP Framework** | `FastMCP` from the official `mcp` Python SDK |
| **Transport** | Streamable HTTP on `/mcp` (port 80 in prod) |
| **Vector DB** | ChromaDB (persistent, cosine similarity) |
| **Embeddings** | `all-MiniLM-L6-v2` via sentence-transformers (384-dim vectors) |
| **Data validation** | Pydantic models |
| **Package mgmt** | `uv` |
| **Client** | Microsoft Copilot Studio (connected via MCP connector) |

## Architecture

```
Copilot Studio / MCP Inspector
        |
        |  HTTP POST
        v
   main.py (entrypoint)
        |
        +-- Parses args (--reindex / --no-reindex / --full-reindex)
        +-- Builds RAGIndex over ./data/
        +-- Calls init_rag(index) to wire into mcp_server module
        +-- Starts FastMCP HTTP server on /mcp
                |
                v
   mcp_server.py (7 tools registered on FastMCP)
        |
        |  calls _get_rag()
        v
   rag_index.py (RAGIndex class)
        |
        +-- Indexing: reads files from ./data/, chunks them, embeds, upserts to ChromaDB
        +-- Search: embeds query -> cosine similarity search in ChromaDB -> returns results
        +-- File listing: enumerates indexed files by type
```

### Modules

- `config.py` — `Settings` dataclass with env var overrides, `SUBFOLDER_MAP` constant mapping subfolder names to source types
- `models.py` — Pydantic models (`SearchResult`, `FormatInfo`, `MappingSetInfo`, `MappingSetDetail`, `FullFileContent`, `MappingContext`)
- `rag_index.py` — `RAGIndex` class: indexing (incremental + full), chunking, search, file listing. Largest module.
- `mcp_server.py` — `FastMCP` instance with 7 registered tools. Module-level `rag` global wired via `init_rag()`
- `main.py` — entrypoint with `argparse`: `--reindex` / `--no-reindex` / `--full-reindex`
- `copilot_agent_instructions.md` — Copilot Studio agent prompt defining trigger words and tool workflows

### Key Design Pattern: Module-Level Global Wiring

`mcp_server.py` uses a module-level `rag: RAGIndex | None` global. `main.py` constructs the index, then calls `init_rag(index)` to inject it. All `@mcp.tool()` functions access it via `_get_rag()`, which raises `RuntimeError` if called before init. Tests use the same pattern with ephemeral ChromaDB instances.

## MCP Tools

1. **`list_formats(extension?)`** — enumerate format definition files
2. **`list_mapping_sets()`** — list mapping sets with source/target info parsed from XML
3. **`get_mapping_set_details(file_path)`** — fetch raw content + metadata for a specific mapping set
4. **`search_docs(query, source_type?, top_k=5)`** — semantic search across all indexed docs (with optional source_type filter)
5. **`search_functions(query, top_k=5)`** — semantic search scoped to function docs only
6. **`find_relevant_mapping_set(query, top_k=3)`** — lightweight discovery returning metadata only (over-fetches 3x, deduplicates by file path)
7. **`generate_mapping_context(source_format, target_format, description?, max_content_chars=50000)`** — returns full file content of reference mapping sets + format definitions + function doc snippets

## Indexing Pipeline

```
./data/
  +-- formats/          -> source_type: "format"
  +-- mapping_sets/     -> source_type: "mapping_set"
  +-- functions_docs/   -> source_type: "functions_doc"
```

1. Files are discovered under `./data/` subfolders
2. Each file is **chunked** based on its type:
   - **Mapping set XML**: summary chunk (one-liner per rule) + rules in batches of 5 with enriched header
   - **Other XML**: by top-level elements
   - **Markdown**: by `##` headers (with `#` heading propagated)
   - **CSV**: by row groups
   - **JSON**: by record groups
3. Chunks are **embedded** in a single batch call to sentence-transformers
4. Embeddings + metadata are **upserted** into ChromaDB

### Incremental Indexing

A SHA-256 file manifest (`file_manifest.json`) tracks what's been indexed. On `--reindex`, only new/changed files are re-processed. Changed files get old chunks deleted first. Removed files are cleaned up.

## Data Flow for a Query

```
User asks Copilot: "Find mapping sets for Format A to Format B"
  -> Copilot calls generate_mapping_context(source_format="A", target_format="B")
    -> RAGIndex embeds the query
    -> ChromaDB cosine similarity search
    -> Returns full file content of matching mapping sets + format defs + function docs
  -> Copilot uses the context to generate/explain mappings
```

## Setup (requires Python 3.10+)

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

## Running the Server

```bash
# Skip indexing, use existing vector store
python main.py --no-reindex

# Incremental: only new/changed files
python main.py --reindex

# Wipe vector store and rebuild
python main.py --full-reindex
```

### Production (port 80)

```bash
# Start
sudo SERVER_PORT=80 .venv/bin/python -u main.py --reindex > /tmp/mcp-server.log 2>&1 &

# Stop
sudo kill $(sudo lsof -ti:80)

# Logs
cat /tmp/mcp-server.log
```

## Running Tests

```bash
pytest tests/ -v
pytest tests/test_chunking.py -v          # single test file
pytest tests/test_rag_index.py -k search  # tests matching keyword
```

Tests use ephemeral ChromaDB instances via `conftest.py` fixtures — no real data or persistent vector store needed.

## Configuration (env vars)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_ROOT_DIR` | `./data` | Root directory for source files |
| `VECTOR_STORE_DIR` | `./vector_store` | ChromaDB persistent storage |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| `SERVER_PORT` | `8000` | HTTP server port |
| `TRANSPORT` | `streamable-http` | MCP transport type |
| `CHUNK_MAX_CHARS` | `1500` | Max characters per chunk |
| `COLLECTION_NAME` | `mcp_rag` | ChromaDB collection name |
| `DEFAULT_TOP_K` | `5` | Default search results count |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Cross-encoder model for reranking |
| `RERANK_OVERSAMPLE` | `4` | Fetch top_k * N candidates before reranking |

If you change the embedding model, delete `./vector_store` and re-index.
