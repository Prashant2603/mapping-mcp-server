"""Entrypoint for the MCP RAG server."""

import logging

from config import settings
from mcp_server import init_rag, mcp
from rag_index import RAGIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Initializing RAG index from %s ...", settings.data_root_dir)
    index = RAGIndex(settings)
    count = index.index_all()
    logger.info("Indexed %d chunks", count)

    init_rag(index)

    logger.info(
        "Starting MCP server (%s) on port %d ...",
        settings.transport,
        settings.server_port,
    )
    mcp.run(transport=settings.transport)


if __name__ == "__main__":
    main()
