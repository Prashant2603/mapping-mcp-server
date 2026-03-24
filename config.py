"""Centralized configuration for the MCP RAG server."""

import os
from dataclasses import dataclass, field


SUBFOLDER_MAP: dict[str, str] = {
    "formats": "format",
    "mapping_sets": "mapping_set",
    "functions_docs": "functions_doc",
}


@dataclass
class Settings:
    """Server settings with environment variable overrides."""

    data_root_dir: str = field(
        default_factory=lambda: os.environ.get("DATA_ROOT_DIR", "./data")
    )
    vector_store_dir: str = field(
        default_factory=lambda: os.environ.get("VECTOR_STORE_DIR", "./vector_store")
    )
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )
    collection_name: str = field(
        default_factory=lambda: os.environ.get("COLLECTION_NAME", "mcp_rag")
    )
    default_top_k: int = field(
        default_factory=lambda: int(os.environ.get("DEFAULT_TOP_K", "5"))
    )
    server_port: int = field(
        default_factory=lambda: int(os.environ.get("SERVER_PORT", "8000"))
    )
    transport: str = field(
        default_factory=lambda: os.environ.get("TRANSPORT", "streamable-http")
    )
    chunk_max_chars: int = field(
        default_factory=lambda: int(os.environ.get("CHUNK_MAX_CHARS", "1500"))
    )


settings = Settings()
