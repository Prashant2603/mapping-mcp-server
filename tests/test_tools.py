"""Tests for MCP tool functions."""

import pytest

from mcp_server import (
    find_relevant_mapping_set,
    generate_mapping_context,
    get_format_definition,
    get_mapping_rules_for_node,
    get_mapping_set_details,
    init_rag,
    list_formats,
    list_mapping_sets,
    list_target_nodes,
    search_docs,
    search_functions,
)


@pytest.fixture(autouse=True)
def _setup_rag(rag_index):
    """Wire the test RAGIndex into mcp_server before each test."""
    init_rag(rag_index)


def test_list_formats():
    result = list_formats()
    assert "items" in result
    assert "total" in result
    assert "has_more" in result
    assert len(result["items"]) >= 1
    for item in result["items"]:
        assert "name" in item
        assert "file_path" in item
        assert "extension" in item


def test_list_formats_filter_xml():
    result = list_formats(extension="xml")
    assert len(result["items"]) >= 1
    for item in result["items"]:
        assert item["extension"] == ".xml"


def test_list_formats_pagination():
    result = list_formats(top_k=1, offset=0)
    assert len(result["items"]) == 1
    assert result["total"] >= 2  # we have xml + csv format files
    assert result["has_more"] is True

    result2 = list_formats(top_k=1, offset=1)
    assert len(result2["items"]) == 1
    assert result2["offset"] == 1


def test_list_mapping_sets():
    result = list_mapping_sets()
    assert "items" in result
    assert "total" in result
    assert len(result["items"]) >= 1
    for item in result["items"]:
        assert "name" in item
        assert "file_path" in item
        assert "source_target_info" in item


def test_list_mapping_sets_source_target():
    result = list_mapping_sets()
    source_targets = [m["source_target_info"] for m in result["items"]]
    assert any("FormatA" in st and "FormatB" in st for st in source_targets)


def test_get_mapping_set_details():
    result = get_mapping_set_details("mapping_sets/sample_mapping.xml")
    assert "raw_content" in result
    assert "mappingSet" in result["raw_content"]
    assert result["metadata"].get("sourceFormat") == "FormatA"
    assert result["metadata"].get("targetFormat") == "FormatB"


def test_search_docs():
    result = search_docs(query="date conversion", top_k=3)
    assert isinstance(result, list)
    assert len(result) > 0
    for item in result:
        assert "source_type" in item
        assert "snippet" in item
        assert "score" in item


def test_search_docs_with_filter():
    result = search_docs(query="format", source_type="format")
    for item in result:
        assert item["source_type"] == "format"


def test_search_docs_invalid_source_type():
    with pytest.raises(ValueError, match="Invalid source_type"):
        search_docs(query="test", source_type="invalid")


def test_search_functions():
    result = search_functions(query="string concatenation")
    assert isinstance(result, list)
    assert len(result) > 0
    for item in result:
        assert item["source_type"] == "functions_doc"


def test_find_relevant_mapping_set():
    result = find_relevant_mapping_set(query="FormatA to FormatB")
    assert isinstance(result, list)
    assert len(result) >= 1
    item = result[0]
    assert "file_path" in item
    assert "source_format" in item
    assert "target_format" in item
    assert "relevance_score" in item
    assert item["source_format"] == "FormatA"
    assert item["target_format"] == "FormatB"


def test_get_format_definition():
    result = get_format_definition("formats/sample_format.xml")
    assert "file_path" in result
    assert "content" in result
    assert "Schema" in result["content"]
    assert "order_id" in result["content"]


def test_get_format_definition_not_found():
    with pytest.raises(FileNotFoundError):
        get_format_definition("formats/nonexistent.xml")


def test_generate_mapping_context_page1():
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
        description="convert orders",
    )
    assert result["page"] == 1
    assert result["total_pages"] >= 3  # at least 1 ms + formats + funcs
    assert result["source_format_query"] == "FormatA"
    assert result["target_format_query"] == "FormatB"
    assert result["page_type"] == "reference_mapping_set"
    assert "reference_mapping_set" in result
    assert "xml_skeleton" in result
    assert "FormatA" in result["xml_skeleton"]
    assert "FormatB" in result["xml_skeleton"]
    assert "summary" in result
    assert "next_page_hint" in result


def test_generate_mapping_context_page1_has_full_content():
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
    )
    ms = result["reference_mapping_set"]
    assert "file_path" in ms
    assert "content" in ms
    assert "mappingSet" in ms["content"]


def test_generate_mapping_context_format_page():
    """The format definitions page should return format files."""
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
    )
    total = result["total_pages"]
    # Format definitions page is after all mapping set pages
    ms_count = result["summary"]["total_reference_mapping_sets"]
    fmt_page = ms_count + 1

    result2 = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
        page=fmt_page,
    )
    assert result2["page_type"] == "format_definitions"
    assert "format_definitions" in result2


def test_generate_mapping_context_funcs_page():
    """The last page should return function documentation."""
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
    )
    total = result["total_pages"]

    result_last = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
        page=total,
    )
    assert result_last["page_type"] == "function_docs"
    assert "relevant_functions" in result_last


def test_generate_mapping_context_page_clamped():
    """Requesting a page beyond total_pages should clamp to last page."""
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
        page=999,
    )
    assert result["page"] == result["total_pages"]


# -- list_target_nodes tests --


def test_list_target_nodes():
    result = list_target_nodes(target_format="FormatB")
    assert result["target_format"] == "FormatB"
    assert result["total_target_paths"] > 0
    assert len(result["nodes"]) > 0
    assert len(result["reference_mapping_sets"]) > 0
    # Should have the /purchase top-level node
    node_names = [n["top_level_node"] for n in result["nodes"]]
    assert "/purchase" in node_names


def test_list_target_nodes_with_source_filter():
    result = list_target_nodes(target_format="FormatB", source_format="FormatA")
    assert result["source_format"] == "FormatA"
    assert result["total_target_paths"] > 0


def test_list_target_nodes_shows_conflicts():
    """Both sample_mapping and alt_mapping target FormatB with different rules
    for /purchase/order_number, so a conflict should be detected."""
    result = list_target_nodes(target_format="FormatB")
    purchase_node = next(
        n for n in result["nodes"] if n["top_level_node"] == "/purchase"
    )
    # order_number exists in both mappings with different functions
    assert purchase_node["has_conflicts"] is True


def test_list_target_nodes_no_match():
    """With a nonsense format, index lookup returns nothing. Semantic search
    may still return some results, so we just verify the tool doesn't crash."""
    result = list_target_nodes(target_format="NonExistentFormat999")
    assert "nodes" in result
    assert "total_target_paths" in result


# -- get_mapping_rules_for_node tests --


def test_get_mapping_rules_for_node():
    result = get_mapping_rules_for_node(
        target_node="/purchase",
        target_format="FormatB",
    )
    assert result["target_node"] == "/purchase"
    assert result["total_rules_found"] > 0
    # Should return rules for /purchase/* paths
    for rule in result["rules"]:
        assert rule["target_path"].startswith("/purchase")
        assert len(rule["candidates"]) > 0


def test_get_mapping_rules_for_node_specific_path():
    result = get_mapping_rules_for_node(
        target_node="/purchase/order_number",
        target_format="FormatB",
    )
    assert result["total_rules_found"] >= 1
    rule = result["rules"][0]
    assert rule["target_path"] == "/purchase/order_number"
    # Should have candidates with XML content
    for candidate in rule["candidates"]:
        assert "xml" in candidate
        assert "function" in candidate


def test_get_mapping_rules_for_node_detects_conflicts():
    """order_number is mapped differently in sample_mapping (substring)
    and alt_mapping (concat)."""
    result = get_mapping_rules_for_node(
        target_node="/purchase/order_number",
        target_format="FormatB",
    )
    rule = result["rules"][0]
    assert rule["has_conflict"] is True
    assert len(rule["candidates"]) >= 2
    funcs = {c["function"] for c in rule["candidates"]}
    assert "substring" in funcs
    assert "concat" in funcs
    assert "conflicts" in result
    assert "conflict_hint" in result


def test_get_mapping_rules_for_node_with_source_filter():
    result = get_mapping_rules_for_node(
        target_node="/purchase",
        target_format="FormatB",
        source_format="FormatA",
    )
    assert result["total_rules_found"] > 0
    # All candidates should be from FormatA source
    for rule in result["rules"]:
        for candidate in rule["candidates"]:
            assert candidate["source_format"] == "FormatA"


def test_get_mapping_rules_for_node_includes_function_docs():
    result = get_mapping_rules_for_node(
        target_node="/purchase",
        target_format="FormatB",
    )
    assert "function_docs" in result


def test_get_mapping_rules_for_node_no_match():
    result = get_mapping_rules_for_node(
        target_node="/nonexistent",
        target_format="FormatB",
    )
    assert result["total_rules_found"] == 0
    assert "no_rules_hint" in result
