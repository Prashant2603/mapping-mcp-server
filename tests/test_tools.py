"""Tests for MCP tool functions."""

import pytest

from mcp_server import (
    find_relevant_mapping_set,
    generate_mapping_context,
    get_mapping_set_details,
    init_rag,
    list_formats,
    list_mapping_sets,
    search_docs,
    search_functions,
)


@pytest.fixture(autouse=True)
def _setup_rag(rag_index):
    """Wire the test RAGIndex into mcp_server before each test."""
    init_rag(rag_index)


def test_list_formats():
    result = list_formats()
    assert isinstance(result, list)
    assert len(result) >= 1
    for item in result:
        assert "name" in item
        assert "file_path" in item
        assert "extension" in item
        assert "short_description" in item


def test_list_formats_filter_xml():
    result = list_formats(extension="xml")
    assert len(result) >= 1
    for item in result:
        assert item["extension"] == ".xml"


def test_list_mapping_sets():
    result = list_mapping_sets()
    assert isinstance(result, list)
    assert len(result) >= 1
    for item in result:
        assert "name" in item
        assert "file_path" in item
        assert "source_target_info" in item


def test_list_mapping_sets_source_target():
    result = list_mapping_sets()
    mapping = result[0]
    assert "FormatA" in mapping["source_target_info"]
    assert "FormatB" in mapping["source_target_info"]


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


def test_generate_mapping_context():
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
        description="convert orders",
    )
    assert "reference_mapping_sets" in result
    assert "format_definitions" in result
    assert "relevant_functions" in result
    assert "xml_skeleton" in result
    assert "source_format_query" in result
    assert result["source_format_query"] == "FormatA"
    assert result["target_format_query"] == "FormatB"
    assert "FormatA" in result["xml_skeleton"]
    assert "FormatB" in result["xml_skeleton"]


def test_generate_mapping_context_returns_full_content():
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
    )
    # reference_mapping_sets should contain full file content, not just snippets
    for ms in result["reference_mapping_sets"]:
        assert "file_path" in ms
        assert "content" in ms
        # Content should be the full XML, not a chunk snippet
        assert "mappingSet" in ms["content"]
