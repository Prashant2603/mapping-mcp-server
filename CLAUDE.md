# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python MCP server with RAG over a local folder structure containing mapping sets (XML), format definitions, and function documentation. Enables LLMs to generate and explore XML mapping sets via MCP tools.

## Architecture

- **Transport**: Streamable HTTP (endpoint: `/mcp`). Default port 8000; production runs on port 80 via `SERVER_PORT=80`
- **MCP SDK**: `FastMCP` from the official `mcp` Python SDK
- **Vector DB**: ChromaDB with persistent storage, cosine similarity
- **Embeddings**: `all-MiniLM-L6-v2` via sentence-transformers (384-dim)
- **Chunking**: File-type-aware — mapping set XML gets enriched headers + grouped rules, other XML by top-level elements, MD by `##` headers with `#` heading propagation, CSV by row groups, JSON by record groups

### Modules
- `config.py` — `Settings` dataclass with env var overrides, `SUBFOLDER_MAP` constant mapping subfolder names → source types
- `models.py` — Pydantic models (`SearchResult`, `FormatInfo`, `MappingSetInfo`, `MappingSetDetail`, `FullFileContent`, `MappingContext`)
- `rag_index.py` — `RAGIndex` class: indexing (incremental + full), chunking, search, file listing. Largest module.
- `mcp_server.py` — `FastMCP` instance with 7 registered tools. Module-level `rag` global wired via `init_rag()`
- `main.py` — entrypoint with `argparse`: `--reindex` / `--no-reindex` / `--full-reindex`
- `copilot_agent_instructions.md` — Copilot Studio agent prompt defining trigger words and tool workflows for the 7 MCP tools

### Key Pattern: Module-Level Global Wiring
`mcp_server.py` uses a module-level `rag: RAGIndex | None` global. `main.py` calls `init_rag(index)` after constructing the `RAGIndex` to wire it in. All `@mcp.tool()` functions access the index via `_get_rag()`, which raises `RuntimeError` if called before init. Tests wire this the same way — see `tests/test_tools.py`.

### Incremental Indexing
`rag_index.py` maintains a SHA-256 file manifest at `{vector_store_dir}/file_manifest.json`. On `--reindex`, only new/changed files are chunked and embedded. Changed files have their old chunks deleted first. Removed files are cleaned up. Embeddings are pre-computed in a single batch call before upserting to ChromaDB.

### Mapping Set Chunking
`_chunk_mapping_set_xml()` extracts `<sourceFormat>`, `<targetFormat>`, `<id>`, `<description>` from the XML and:
1. Creates a **summary chunk** with a one-liner per mapping rule (best match for broad queries)
2. Groups **mapping rules in batches of 5** with the enriched header prepended
3. Stores `source_format`, `target_format`, `mapping_functions` in chunk metadata for filtering

### MCP Tools
- `list_formats(extension?)` — list format files
- `list_mapping_sets()` — list mapping sets with source/target info parsed from XML
- `get_mapping_set_details(file_path)` — raw content + metadata
- `search_docs(query, source_type?, top_k=5)` — semantic search, optional filter
- `search_functions(query, top_k=5)` — search function docs only
- `find_relevant_mapping_set(query, top_k=3)` — lightweight discovery returning metadata only. Internally over-fetches `top_k * 3` chunks then deduplicates by file path
- `generate_mapping_context(source_format, target_format, description?, max_content_chars=50000)` — returns **full file content** of reference mapping sets + format definitions + function doc snippets

## Development

### Setup (requires Python 3.10+)
```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Run server (flag is mandatory)
```bash
python main.py --no-reindex          # skip indexing, use existing vector store
python main.py --reindex             # incremental: only new/changed files
python main.py --full-reindex        # wipe vector store and rebuild
```

### Run tests
```bash
pytest tests/ -v
pytest tests/test_chunking.py -v          # single test file
pytest tests/test_rag_index.py -k search  # tests matching keyword
```

### MCP Inspector (interactive tool testing)
```bash
mcp dev main.py
```

### Production (port 80, requires sudo)
```bash
# Start
sudo SERVER_PORT=80 .venv/bin/python -u main.py --reindex > /tmp/mcp-server.log 2>&1 &
# Stop
sudo kill $(sudo lsof -ti:80)
# Logs
cat /tmp/mcp-server.log
```

### Configuration (env vars or `config.py` defaults)
- `DATA_ROOT_DIR` (default: `./data`)
- `VECTOR_STORE_DIR` (default: `./vector_store`)
- `EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`)
- `SERVER_PORT` (default: `8000`)
- `TRANSPORT` (default: `streamable-http`)
- `CHUNK_MAX_CHARS` (default: `1500`)
- `COLLECTION_NAME` (default: `mcp_rag`)
- `DEFAULT_TOP_K` (default: `5`)

If you change the embedding model, delete `./vector_store` and re-index.

### Test Architecture
Tests use ephemeral ChromaDB instances via `conftest.py` fixtures — `data_dir` creates a tmp directory with sample XML/CSV/MD files, `rag_index` builds a throwaway index over them. No real data or persistent vector store needed. Test files: `test_chunking`, `test_incremental`, `test_main`, `test_rag_index`, `test_tools`.

## Domain Concepts

- **Mapping Set**: XML file describing how to convert Format A → Format B using functions from a custom library
- **Format**: Schema/structure file (XML/CSV/JSON) describing inputs or outputs
- **Functions Docs**: Markdown/text docs describing available mapping functions (names, params, examples)
- **source_type**: The `SUBFOLDER_MAP` in `config.py` maps directory names to source types used in ChromaDB metadata filtering (`formats/` → `"format"`, `mapping_sets/` → `"mapping_set"`, `functions_docs/` → `"functions_doc"`)
