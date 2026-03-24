# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python MCP server with RAG over a local folder structure containing mapping sets (XML), format definitions, and function documentation. Enables LLMs to generate and explore XML mapping sets via MCP tools.

## Architecture

- **Transport**: Streamable HTTP on port 8000 (endpoint: `http://localhost:8000/mcp`)
- **MCP SDK**: `FastMCP` from the official `mcp` Python SDK
- **Vector DB**: ChromaDB with persistent storage, cosine similarity
- **Embeddings**: `all-MiniLM-L6-v2` via sentence-transformers (384-dim)
- **Chunking**: File-type-aware — XML by top-level elements, MD by `##` headers, CSV by row groups, JSON by record groups

### Modules
- `config.py` — `Settings` dataclass with env var overrides, `SUBFOLDER_MAP` constant
- `models.py` — Pydantic models (`SearchResult`, `FormatInfo`, `MappingSetInfo`, `MappingSetDetail`, `MappingContext`)
- `rag_index.py` — `RAGIndex` class: indexing, chunking, search, file listing. Largest module.
- `mcp_server.py` — `FastMCP` instance with 6 registered tools. Module-level `rag` global wired via `init_rag()`
- `main.py` — entrypoint: init RAGIndex → index_all → init_rag → mcp.run()

### MCP Tools
- `list_formats(extension?)` — list format files
- `list_mapping_sets()` — list mapping sets with source/target info parsed from XML
- `get_mapping_set_details(file_path)` — raw content + metadata
- `search_docs(query, source_type?, top_k=5)` — semantic search, optional filter
- `search_functions(query, top_k=5)` — search function docs only
- `generate_mapping_context(source_format, target_format, description?)` — bundled context for XML generation

### Data Layout
```
data/
  formats/          → source_type: "format"
  mapping_sets/     → source_type: "mapping_set"
  functions_docs/   → source_type: "functions_doc"
```

## Development

### Setup (requires Python 3.10+)
```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

### Run server
```bash
python main.py
```

### Run tests
```bash
pytest tests/ -v
```

### MCP Inspector (interactive tool testing)
```bash
mcp dev main.py
```

### Configuration (env vars or `config.py` defaults)
- `DATA_ROOT_DIR` (default: `./data`)
- `VECTOR_STORE_DIR` (default: `./vector_store`)
- `EMBEDDING_MODEL` (default: `all-MiniLM-L6-v2`)
- `SERVER_PORT` (default: `8000`)
- `CHUNK_MAX_CHARS` (default: `1500`)

If you change the embedding model, delete `./vector_store` and re-index.

## Domain Concepts

- **Mapping Set**: XML file describing how to convert Target A → Target B using functions from a custom library
- **Format**: Schema/structure file (XML/CSV/JSON) describing inputs or outputs
- **Functions Docs**: Markdown/text docs describing available mapping functions (names, params, examples)
