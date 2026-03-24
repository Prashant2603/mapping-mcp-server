"""Tests for MCP tool functions."""

import pytest

from mcp_server import (
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
    # Sample mapping has source="FormatA" target="FormatB"
    mapping = result[0]
    assert "FormatA" in mapping["source_target_info"]
    assert "FormatB" in mapping["source_target_info"]


def test_get_mapping_set_details():
    result = get_mapping_set_details("mapping_sets/sample_mapping.xml")
    assert "raw_content" in result
    assert "MappingSet" in result["raw_content"]
    assert result["metadata"].get("source") == "FormatA"
    assert result["metadata"].get("target") == "FormatB"


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


def test_generate_mapping_context():
    result = generate_mapping_context(
        source_format="FormatA",
        target_format="FormatB",
        description="convert orders",
    )
    assert "relevant_formats" in result
    assert "similar_mapping_sets" in result
    assert "relevant_functions" in result
    assert "xml_skeleton" in result
    assert "FormatA" in result["xml_skeleton"]
    assert "FormatB" in result["xml_skeleton"]
