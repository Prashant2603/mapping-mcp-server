"""MCP server with tool registration using FastMCP."""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import settings
from models import (
    FormatInfo,
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


@mcp.tool()
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
            root = ET.fromstring(content)
            # Try child elements first (e.g. <sourceFormat>, <targetFormat>)
            src_el = root.find("sourceFormat")
            tgt_el = root.find("targetFormat")
            src = src_el.text if src_el is not None and src_el.text else root.attrib.get("source", "")
            tgt = tgt_el.text if tgt_el is not None and tgt_el.text else root.attrib.get("target", "")
            if src or tgt:
                source_target = f"{src} -> {tgt}"
            # Try child elements for description/id, then root attributes
            desc_el = root.find("description")
            id_el = root.find("id")
            summary = (
                (desc_el.text if desc_el is not None and desc_el.text else "")
                or (id_el.text if id_el is not None and id_el.text else "")
                or root.attrib.get("name", "")
            )
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
def generate_mapping_context(
    source_format: str,
    target_format: str,
    description: str | None = None,
) -> dict:
    """Prepare all relevant context needed to generate a new mapping set XML.

    Gathers relevant formats, similar existing mapping sets, and function documentation
    so that an LLM can generate the final XML mapping set.

    Args:
        source_format: Identifier of the source format (e.g. "EDIFACT_D96A").
        target_format: Identifier of the target format (e.g. "X12_850").
        description: Optional natural-language description of the mapping request.

    Returns:
        Context bundle with relevant_formats, similar_mapping_sets, relevant_functions,
        and a suggested XML skeleton template.
    """
    index = _get_rag()
    composite_query = f"mapping from {source_format} to {target_format}"
    if description:
        composite_query += f" - {description}"

    relevant_formats = index.search(composite_query, source_type="format", top_k=3)
    similar_mappings = index.search(
        composite_query, source_type="mapping_set", top_k=3
    )
    relevant_functions = index.search(
        composite_query, source_type="functions_doc", top_k=5
    )

    xml_skeleton = f"""<?xml version="1.0"?>
<MappingSet source="{source_format}" target="{target_format}" version="1.0">
  <!-- Add mapping rules here using available functions -->
  <MappingRule source_path="" target_path="">
    <Function name="" params=""/>
  </MappingRule>
</MappingSet>"""

    return MappingContext(
        relevant_formats=relevant_formats,
        similar_mapping_sets=similar_mappings,
        relevant_functions=relevant_functions,
        xml_skeleton=xml_skeleton,
    ).model_dump()
