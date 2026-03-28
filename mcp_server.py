"""MCP server with tool registration using FastMCP."""

import functools
import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import settings
from models import (
    FormatInfo,
    FullFileContent,
    MappingContext,
    MappingSetDetail,
    MappingSetInfo,
    SearchResult,
)
from rag_index import RAGIndex

logger = logging.getLogger(__name__)

mcp = FastMCP("MappingRAG", host="0.0.0.0", port=settings.server_port)

rag: RAGIndex | None = None


def init_rag(index: RAGIndex) -> None:
    """Wire the RAGIndex instance into this module."""
    global rag
    rag = index


def _get_rag() -> RAGIndex:
    if rag is None:
        raise RuntimeError("RAGIndex not initialized")
    return rag


def _log_tool(func):
    """Decorator that logs tool invocation, arguments, and elapsed time."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        params = ", ".join(
            [repr(a) for a in args]
            + [f"{k}={v!r}" for k, v in kwargs.items()]
        )
        logger.info("-> %s(%s)", func.__name__, params)
        start = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            # Summarize result size for readability
            if isinstance(result, list):
                summary = f"{len(result)} items"
            elif isinstance(result, dict):
                summary = f"dict with {len(result)} keys"
            else:
                summary = type(result).__name__
            # Log response payload size
            import json
            try:
                payload_size = len(json.dumps(result, default=str))
                summary += f", {payload_size:,} chars"
            except Exception:
                pass
            logger.info("<- %s completed in %.1fms — returned %s", func.__name__, elapsed, summary)
            return result
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error("<- %s failed in %.1fms — %s: %s", func.__name__, elapsed, type(exc).__name__, exc)
            raise

    return wrapper


def _parse_mapping_set_metadata(content: str) -> dict:
    """Extract source/target/description from mapping set XML."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {}
    src = (root.findtext("sourceFormat") or root.attrib.get("source", "")).strip()
    tgt = (root.findtext("targetFormat") or root.attrib.get("target", "")).strip()
    desc = (root.findtext("description") or root.attrib.get("name", "")).strip()
    ms_id = (root.findtext("id") or "").strip()
    return {
        "source_format": src,
        "target_format": tgt,
        "description": desc,
        "id": ms_id,
    }


@mcp.tool()
@_log_tool
def list_formats(extension: str | None = None) -> list[dict]:
    """List all known format files with basic info.

    Args:
        extension: Optional filter by file extension (e.g. "xml", "csv", "json").

    Returns:
        List of format files with name, file_path, extension, and short_description.
    """
    index = _get_rag()
    files = index.list_files("format", extension)
    results: list[dict] = []
    for f in files:
        short_desc = ""
        try:
            content = index.get_file_content(f["file_path"])
            short_desc = content[:200].replace("\n", " ").strip()
        except Exception:
            pass
        results.append(
            FormatInfo(
                name=f["name"],
                file_path=f["file_path"],
                extension=f["extension"],
                short_description=short_desc,
            ).model_dump()
        )
    return results


@mcp.tool()
@_log_tool
def list_mapping_sets() -> list[dict]:
    """List all available mapping sets with source/target info.

    Returns:
        List of mapping sets with name, file_path, source_target_info, and summary.
    """
    index = _get_rag()
    files = index.list_files("mapping_set")
    results: list[dict] = []
    for f in files:
        source_target = ""
        summary = ""
        try:
            content = index.get_file_content(f["file_path"])
            meta = _parse_mapping_set_metadata(content)
            src = meta.get("source_format", "")
            tgt = meta.get("target_format", "")
            if src or tgt:
                source_target = f"{src} -> {tgt}"
            summary = meta.get("description", "") or meta.get("id", "")
        except Exception:
            pass
        results.append(
            MappingSetInfo(
                name=f["name"],
                file_path=f["file_path"],
                source_target_info=source_target,
                summary=summary,
            ).model_dump()
        )
    return results


@mcp.tool()
@_log_tool
def get_mapping_set_details(file_path: str) -> dict:
    """Get the full content of a specific mapping set.

    Args:
        file_path: Path to the mapping set file (relative to data root).

    Returns:
        Raw content and optional parsed metadata.
    """
    index = _get_rag()
    content = index.get_file_content(file_path)
    metadata: dict = {}
    try:
        root = ET.fromstring(content)
        metadata = dict(root.attrib)
        metadata["root_tag"] = root.tag
        metadata["child_count"] = len(list(root))
        # Extract key child element text for mapping set metadata
        for tag in ("id", "sourceFormat", "targetFormat", "description", "version"):
            el = root.find(tag)
            if el is not None and el.text:
                metadata[tag] = el.text
    except ET.ParseError:
        pass
    return MappingSetDetail(
        file_path=file_path,
        raw_content=content,
        metadata=metadata,
    ).model_dump()


@mcp.tool()
@_log_tool
def search_docs(
    query: str,
    source_type: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    """Semantic search over all indexed content (formats, mapping sets, function docs).

    Args:
        query: Natural language search query.
        source_type: Optional filter - one of 'format', 'mapping_set', 'functions_doc'.
        top_k: Number of results to return (default 5).

    Returns:
        List of results with source_type, file_path, snippet, and relevance score.
    """
    valid_types = {"format", "mapping_set", "functions_doc"}
    if source_type and source_type not in valid_types:
        raise ValueError(
            f"Invalid source_type '{source_type}'. Must be one of: {valid_types}"
        )
    index = _get_rag()
    results = index.search(query, source_type, top_k)
    return [r.model_dump() for r in results]


@mcp.tool()
@_log_tool
def search_functions(query: str, top_k: int = 5) -> list[dict]:
    """Semantic search focused only on function documentation.

    Args:
        query: Natural language search query about functions.
        top_k: Number of results to return (default 5).

    Returns:
        List of results with source_type, file_path, snippet, and relevance score.
    """
    index = _get_rag()
    results = index.search(query, source_type="functions_doc", top_k=top_k)
    return [r.model_dump() for r in results]


@mcp.tool()
@_log_tool
def find_relevant_mapping_set(query: str, top_k: int = 3) -> list[dict]:
    """Find mapping sets most relevant to a query. Returns metadata only, not full content.

    Use get_mapping_set_details() to retrieve the full content of a specific mapping set.

    Args:
        query: Natural language query (e.g. "SMRV4 to pain.001" or "settlement message mapping").
        top_k: Maximum number of mapping sets to return (default 3).

    Returns:
        List of mapping sets with file_path, source_format, target_format, description, and relevance_score.
    """
    index = _get_rag()
    results = index.search(query, source_type="mapping_set", top_k=top_k * 3)

    # Deduplicate by file_path and enrich with parsed metadata
    seen: set[str] = set()
    output: list[dict] = []
    for r in results:
        if r.file_path in seen:
            continue
        seen.add(r.file_path)
        meta = {}
        try:
            content = index.get_file_content(r.file_path)
            meta = _parse_mapping_set_metadata(content)
        except Exception:
            pass
        output.append({
            "file_path": r.file_path,
            "source_format": meta.get("source_format", ""),
            "target_format": meta.get("target_format", ""),
            "description": meta.get("description", ""),
            "relevance_score": r.score,
        })
        if len(output) >= top_k:
            break
    return output


@mcp.tool()
@_log_tool
def generate_mapping_context(
    source_format: str,
    target_format: str,
    description: str | None = None,
    max_content_chars: int = 50000,
) -> dict:
    """Prepare all relevant context needed to generate a new mapping set XML.

    Gathers full content of the most relevant existing mapping sets and format
    definitions, plus function documentation snippets, so that an LLM can
    generate the final XML mapping set.

    Args:
        source_format: Identifier of the source format (e.g. "SettlementMessageRequestV4").
        target_format: Identifier of the target format (e.g. "pain.001.001.02").
        description: Optional natural-language description of the mapping request.
        max_content_chars: Maximum characters per file content (default 50000).
            Files exceeding this are truncated with a note to use get_mapping_set_details.

    Returns:
        Context bundle with reference_mapping_sets (full content), format_definitions
        (full content), relevant_functions (snippets), and a suggested XML skeleton.
    """
    index = _get_rag()
    query = f"mapping from {source_format} to {target_format}"
    if description:
        query += f" {description}"

    # Step 1: Find relevant mapping sets via semantic search, deduplicate by file
    similar = index.search(query, source_type="mapping_set", top_k=9)
    seen_ms: set[str] = set()
    reference_mapping_sets: list[FullFileContent] = []
    for result in similar:
        if result.file_path in seen_ms:
            continue
        seen_ms.add(result.file_path)
        try:
            content = index.get_file_content(result.file_path)
            if len(content) > max_content_chars:
                content = (
                    content[:max_content_chars]
                    + f"\n\n[Truncated at {max_content_chars} chars. "
                    f"Use get_mapping_set_details('{result.file_path}') for full content.]"
                )
            reference_mapping_sets.append(
                FullFileContent(file_path=result.file_path, content=content)
            )
        except Exception:
            pass
        if len(reference_mapping_sets) >= 3:
            break

    # Step 2: Find relevant format definitions, deduplicate by file
    format_query = f"{source_format} {target_format} format schema"
    format_results = index.search(format_query, source_type="format", top_k=9)
    seen_fmt: set[str] = set()
    format_definitions: list[FullFileContent] = []
    for result in format_results:
        if result.file_path in seen_fmt:
            continue
        seen_fmt.add(result.file_path)
        try:
            content = index.get_file_content(result.file_path)
            if len(content) > max_content_chars:
                content = (
                    content[:max_content_chars]
                    + f"\n\n[Truncated at {max_content_chars} chars.]"
                )
            format_definitions.append(
                FullFileContent(file_path=result.file_path, content=content)
            )
        except Exception:
            pass
        if len(format_definitions) >= 3:
            break

    # Step 3: Get relevant function docs (snippets are fine)
    func_results = index.search(query, source_type="functions_doc", top_k=5)

    xml_skeleton = f"""<?xml version="1.0"?>
<MappingSet source="{source_format}" target="{target_format}" version="1.0">
  <!-- Add mapping rules here using available functions -->
  <MappingRule source_path="" target_path="">
    <Function name="" params=""/>
  </MappingRule>
</MappingSet>"""

    return MappingContext(
        source_format_query=source_format,
        target_format_query=target_format,
        reference_mapping_sets=reference_mapping_sets,
        format_definitions=format_definitions,
        relevant_functions=func_results,
        xml_skeleton=xml_skeleton,
    ).model_dump()
