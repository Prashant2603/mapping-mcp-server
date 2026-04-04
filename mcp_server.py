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
    entries = index.lookup(source_type="format", extension=extension)
    return [
        FormatInfo(
            name=e["name"],
            file_path=e["file_path"],
            extension=e["extension"],
            short_description=e.get("short_description", ""),
        ).model_dump()
        for e in entries
    ]


@mcp.tool()
@_log_tool
def list_mapping_sets() -> list[dict]:
    """List all available mapping sets with source/target info.

    Returns:
        List of mapping sets with name, file_path, source_target_info, and summary.
    """
    index = _get_rag()
    entries = index.lookup(source_type="mapping_set")
    results: list[dict] = []
    for e in entries:
        src = e.get("source_format", "")
        tgt = e.get("target_format", "")
        source_target = f"{src} -> {tgt}" if src or tgt else ""
        summary = e.get("description", "") or e.get("id", "")
        results.append(
            MappingSetInfo(
                name=e["name"],
                file_path=e["file_path"],
                source_target_info=source_target,
                summary=summary,
            ).model_dump()
        )
    return results


@mcp.tool()
@_log_tool
def get_format_definition(file_path: str) -> dict:
    """Get the full content of a specific format definition file.

    Args:
        file_path: Path to the format file (relative to data root).
            Get file_path from list_formats() or search_docs() first.

    Returns:
        File path and full raw content of the format definition.
    """
    index = _get_rag()
    content = index.get_file_content(file_path)
    return FullFileContent(
        file_path=file_path,
        content=content,
    ).model_dump()


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


def _parse_mapping_rules(content: str) -> list[dict]:
    """Extract all mapping rules from a mapping set XML string.

    Returns list of dicts with target, function, parameters, description,
    and the raw XML of the rule.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    rules: list[dict] = []
    for mapping in root.findall("mapping"):
        target_el = mapping.find("target")
        func_el = mapping.find("function")
        param_el = mapping.find("parameter")
        desc_el = mapping.find("description")
        rules.append({
            "target": (target_el.text or "").strip() if target_el is not None else "",
            "function": (func_el.text or "").strip() if func_el is not None else "",
            "parameters": (param_el.text or "").strip() if param_el is not None else "",
            "description": (desc_el.text or "").strip() if desc_el is not None else "",
            "xml": ET.tostring(mapping, encoding="unicode"),
        })
    return rules


def _get_top_level_node(target_path: str) -> str:
    """Extract the top-level node from a target path like /purchase/order_number -> /purchase."""
    parts = target_path.strip("/").split("/")
    return f"/{parts[0]}" if parts and parts[0] else target_path


@mcp.tool()
@_log_tool
def list_target_nodes(
    target_format: str,
    source_format: str | None = None,
) -> dict:
    """List all target nodes that need to be mapped, extracted from existing mapping sets.

    Finds mapping sets that share the same target format (and optionally source format),
    then extracts all unique target paths grouped by top-level node.

    Use this as the starting point for incremental mapping set creation — it tells you
    which nodes exist and how many rules each has in reference mapping sets.

    Args:
        target_format: The target format to find nodes for (e.g. "pain.001.001.02").
        source_format: Optional source format filter to narrow results.

    Returns:
        Dict with target_format, reference mapping sets found, and nodes grouped by
        top-level path with rule counts.
    """
    index = _get_rag()

    # Find mapping sets with matching target format
    matches = index.lookup(
        source_type="mapping_set",
        target_format=target_format,
    )
    if source_format:
        # Further filter by source format
        exact = index.lookup(
            source_type="mapping_set",
            source_format=source_format,
            target_format=target_format,
        )
        if exact:
            matches = exact

    # Fall back to semantic search if no index matches
    if not matches:
        query = f"mapping to {target_format}"
        if source_format:
            query = f"mapping from {source_format} to {target_format}"
        results = index.search(query, source_type="mapping_set", top_k=9)
        seen: set[str] = set()
        for r in results:
            if r.file_path not in seen:
                seen.add(r.file_path)
                matches.append({"file_path": r.file_path})
            if len(matches) >= 3:
                break

    # Extract all target paths from matched mapping sets
    reference_files: list[dict] = []
    all_targets: dict[str, list[dict]] = {}  # target_path -> list of {source_file, function, ...}

    for entry in matches[:5]:
        fp = entry["file_path"]
        try:
            content = index.get_file_content(fp)
        except Exception:
            continue

        meta = _parse_mapping_set_metadata(content)
        rules = _parse_mapping_rules(content)
        reference_files.append({
            "file_path": fp,
            "source_format": meta.get("source_format", ""),
            "target_format": meta.get("target_format", ""),
            "rule_count": len(rules),
        })

        for rule in rules:
            target_path = rule["target"]
            if target_path not in all_targets:
                all_targets[target_path] = []
            all_targets[target_path].append({
                "source_file": fp,
                "function": rule["function"],
                "description": rule["description"],
            })

    # Group by top-level node
    groups: dict[str, list[dict]] = {}
    for target_path, sources in sorted(all_targets.items()):
        top_node = _get_top_level_node(target_path)
        if top_node not in groups:
            groups[top_node] = []
        has_conflict = len(set(s["source_file"] for s in sources)) > 1
        groups[top_node].append({
            "target_path": target_path,
            "reference_count": len(sources),
            "has_conflict": has_conflict,
            "references": sources,
        })

    # Build ordered node list with counts
    node_summary: list[dict] = []
    for top_node, entries in groups.items():
        node_summary.append({
            "top_level_node": top_node,
            "total_rules": len(entries),
            "has_conflicts": any(e["has_conflict"] for e in entries),
            "target_paths": [e["target_path"] for e in entries],
        })

    return {
        "target_format": target_format,
        "source_format": source_format or "",
        "reference_mapping_sets": reference_files,
        "total_target_paths": len(all_targets),
        "nodes": node_summary,
        "hint": "Call get_mapping_rules_for_node() for each top_level_node to get rules incrementally.",
    }


@mcp.tool()
@_log_tool
def get_mapping_rules_for_node(
    target_node: str,
    target_format: str,
    source_format: str | None = None,
) -> dict:
    """Get existing mapping rules for a specific target node from reference mapping sets.

    Searches mapping sets that share the target format and returns all rules whose
    target path starts with the given node. When multiple reference mapping sets
    have rules for the same target path, all candidates are returned so you can
    detect conflicts and ask the user which to prefer.

    Args:
        target_node: The target node path to get rules for (e.g. "/purchase" or
            "/purchase/order_number"). Returns rules for this path and all children.
        target_format: The target format to search within.
        source_format: Optional source format filter.

    Returns:
        Dict with the node, matched rules grouped by target_path, conflict flags,
        and relevant function doc snippets.
    """
    index = _get_rag()

    # Find mapping sets with matching formats
    matches = index.lookup(
        source_type="mapping_set",
        target_format=target_format,
    )
    if source_format:
        exact = index.lookup(
            source_type="mapping_set",
            source_format=source_format,
            target_format=target_format,
        )
        if exact:
            matches = exact

    # Fall back to semantic search
    if not matches:
        query = f"mapping to {target_format} {target_node}"
        results = index.search(query, source_type="mapping_set", top_k=9)
        seen: set[str] = set()
        for r in results:
            if r.file_path not in seen:
                seen.add(r.file_path)
                matches.append({"file_path": r.file_path})
            if len(matches) >= 5:
                break

    # Normalize node path for matching
    node_normalized = target_node.rstrip("/")

    # Collect rules matching this node
    rules_by_target: dict[str, list[dict]] = {}
    func_names: set[str] = set()

    for entry in matches[:5]:
        fp = entry["file_path"]
        try:
            content = index.get_file_content(fp)
        except Exception:
            continue

        meta = _parse_mapping_set_metadata(content)
        rules = _parse_mapping_rules(content)

        for rule in rules:
            target_path = rule["target"]
            # Match if target_path starts with the node (exact or child)
            if target_path == node_normalized or target_path.startswith(node_normalized + "/"):
                if target_path not in rules_by_target:
                    rules_by_target[target_path] = []
                rules_by_target[target_path].append({
                    "source_file": fp,
                    "source_format": meta.get("source_format", ""),
                    "target_format": meta.get("target_format", ""),
                    "function": rule["function"],
                    "parameters": rule["parameters"],
                    "description": rule["description"],
                    "xml": rule["xml"],
                })
                if rule["function"]:
                    func_names.add(rule["function"])

    # Build response with conflict detection
    rule_entries: list[dict] = []
    conflicts: list[str] = []

    for target_path in sorted(rules_by_target.keys()):
        candidates = rules_by_target[target_path]
        has_conflict = len(candidates) > 1 and len(
            set((c["function"], c["parameters"]) for c in candidates)
        ) > 1

        if has_conflict:
            conflicts.append(target_path)

        rule_entries.append({
            "target_path": target_path,
            "has_conflict": has_conflict,
            "candidates": candidates,
        })

    # Fetch function docs for functions used in these rules
    func_docs: list[dict] = []
    if func_names:
        func_query = " ".join(func_names)
        func_results = index.search(func_query, source_type="functions_doc", top_k=3)
        func_docs = [r.model_dump() for r in func_results]

    result: dict = {
        "target_node": target_node,
        "target_format": target_format,
        "source_format": source_format or "",
        "total_rules_found": len(rule_entries),
        "rules": rule_entries,
        "function_docs": func_docs,
    }

    if conflicts:
        result["conflicts"] = conflicts
        result["conflict_hint"] = (
            "Multiple reference mapping sets have different rules for these target paths. "
            "Present all candidates to the user and ask which they prefer."
        )

    if not rule_entries:
        result["no_rules_hint"] = (
            "No existing rules found for this node. Use search_functions() to find "
            "appropriate functions and generate rules from scratch."
        )

    return result


@mcp.tool()
@_log_tool
def generate_mapping_context(
    source_format: str,
    target_format: str,
    description: str | None = None,
    page: int = 1,
    max_content_chars: int = 50000,
) -> dict:
    """Prepare context needed to generate a new mapping set XML, returned in pages.

    Call with page=1 first to get an overview with the best reference mapping set,
    then increment page to get additional context one piece at a time.

    Page contents:
      - Page 1: Overview + best reference mapping set (exact or semantic match)
      - Page 2: Second reference mapping set (if available)
      - Page 3: Third reference mapping set (if available)
      - Page 4: Format definitions (source + target)
      - Page 5: Function documentation snippets

    Each page response includes total_pages so you know when to stop.
    For large mapping sets, prefer get_mapping_set_details() and
    get_format_definition() to fetch individual files directly.

    Args:
        source_format: Identifier of the source format (e.g. "SettlementMessageRequestV4").
        target_format: Identifier of the target format (e.g. "pain.001.001.02").
        description: Optional natural-language description of the mapping request.
        page: Page number starting at 1. Default 1.
        max_content_chars: Maximum characters per file content (default 50000).

    Returns:
        Paginated context with page info, content for the requested page,
        and guidance on what to fetch next.
    """
    index = _get_rag()
    query = f"mapping from {source_format} to {target_format}"
    if description:
        query += f" {description}"

    # -- Gather all candidate file paths (lightweight, no content yet) --

    # Reference mapping sets: exact index lookup + semantic search
    exact_ms = index.lookup(
        source_type="mapping_set",
        source_format=source_format,
        target_format=target_format,
    )
    seen_ms: set[str] = set()
    ms_file_paths: list[str] = []

    for entry in exact_ms:
        fp = entry["file_path"]
        if fp not in seen_ms:
            seen_ms.add(fp)
            ms_file_paths.append(fp)
        if len(ms_file_paths) >= 3:
            break

    if len(ms_file_paths) < 3:
        similar = index.search(query, source_type="mapping_set", top_k=9)
        for result in similar:
            if result.file_path not in seen_ms:
                seen_ms.add(result.file_path)
                ms_file_paths.append(result.file_path)
            if len(ms_file_paths) >= 3:
                break

    # Format definitions: index lookup by name + semantic search
    format_names = [source_format, target_format]
    seen_fmt: set[str] = set()
    fmt_file_paths: list[str] = []

    all_formats = index.lookup(source_type="format")
    for entry in all_formats:
        name_lower = entry["name"].lower()
        if any(fn.lower() in name_lower or name_lower in fn.lower() for fn in format_names if fn):
            fp = entry["file_path"]
            if fp not in seen_fmt:
                seen_fmt.add(fp)
                fmt_file_paths.append(fp)
            if len(fmt_file_paths) >= 3:
                break

    if len(fmt_file_paths) < 3:
        format_query = f"{source_format} {target_format} format schema"
        format_results = index.search(format_query, source_type="format", top_k=9)
        for result in format_results:
            if result.file_path not in seen_fmt:
                seen_fmt.add(result.file_path)
                fmt_file_paths.append(result.file_path)
            if len(fmt_file_paths) >= 3:
                break

    # -- Calculate total pages based on available data --
    # Pages 1..N: one reference mapping set each (only if available)
    # Page N+1: format definitions
    # Page N+2: function docs
    ms_pages = len(ms_file_paths)  # 0-3
    total_pages = ms_pages + 2  # +1 for formats, +1 for function docs

    # Clamp page to valid range
    page = max(1, min(page, total_pages))

    # -- Helper to read a file with truncation --
    def _read_file(fp: str) -> FullFileContent:
        content = index.get_file_content(fp)
        if len(content) > max_content_chars:
            content = (
                content[:max_content_chars]
                + f"\n\n[Truncated at {max_content_chars} chars. "
                f"Use get_mapping_set_details('{fp}') for full content.]"
            )
        return FullFileContent(file_path=fp, content=content)

    # -- Build response for the requested page --
    result: dict = {
        "source_format_query": source_format,
        "target_format_query": target_format,
        "page": page,
        "total_pages": total_pages,
    }

    if page <= ms_pages:
        # Pages 1..N: one reference mapping set per page
        fp = ms_file_paths[page - 1]
        try:
            ms_content = _read_file(fp)
        except Exception:
            ms_content = FullFileContent(file_path=fp, content="[Error reading file]")

        result["page_type"] = "reference_mapping_set"
        result["reference_mapping_set"] = ms_content.model_dump()
        result["summary"] = {
            "total_reference_mapping_sets": len(ms_file_paths),
            "total_format_definitions": len(fmt_file_paths),
            "reference_files": ms_file_paths,
            "format_files": fmt_file_paths,
        }

        if page == 1:
            result["xml_skeleton"] = (
                f'<?xml version="1.0"?>\n'
                f'<MappingSet source="{source_format}" target="{target_format}" version="1.0">\n'
                f"  <!-- Add mapping rules here using available functions -->\n"
                f'  <MappingRule source_path="" target_path="">\n'
                f'    <Function name="" params=""/>\n'
                f"  </MappingRule>\n"
                f"</MappingSet>"
            )

        if page < total_pages:
            result["next_page_hint"] = (
                f"Call generate_mapping_context with page={page + 1} for more context."
            )

    elif page == ms_pages + 1:
        # Format definitions page
        format_definitions: list[dict] = []
        for fp in fmt_file_paths:
            try:
                format_definitions.append(_read_file(fp).model_dump())
            except Exception:
                pass

        result["page_type"] = "format_definitions"
        result["format_definitions"] = format_definitions

        if page < total_pages:
            result["next_page_hint"] = (
                f"Call generate_mapping_context with page={page + 1} for function docs."
            )

    elif page == ms_pages + 2:
        # Function documentation page
        func_results = index.search(query, source_type="functions_doc", top_k=5)
        result["page_type"] = "function_docs"
        result["relevant_functions"] = [r.model_dump() for r in func_results]

    return result
