"""Entrypoint for the MCP RAG server."""

import argparse
import logging

from config import settings
from mcp_server import init_rag, mcp
from rag_index import RAGIndex

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MCP RAG Server")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--reindex",
        action="store_true",
        help="Incremental index: only process new/changed files",
    )
    group.add_argument(
        "--no-reindex",
        action="store_true",
        help="Skip indexing, use existing vector store",
    )
    group.add_argument(
        "--full-reindex",
        action="store_true",
        help="Wipe vector store and re-index everything from scratch",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("Initializing RAG index from %s ...", settings.data_root_dir)
    index = RAGIndex(settings)

    if args.no_reindex:
        count = index.collection_count()
        if count == 0:
            logger.warning(
                "Vector store is empty. You may need to run with --reindex."
            )
        else:
            logger.info("Using existing vector store (%d chunks)", count)
    elif args.full_reindex:
        logger.info("Full re-index: wiping vector store...")
        index.reset_collection()
        count = index.index_all(incremental=False)
        logger.info("Indexed %d chunks", count)
    else:
        # --reindex (incremental)
        count = index.index_all(incremental=True)
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
