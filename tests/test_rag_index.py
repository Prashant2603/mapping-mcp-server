"""Tests for RAGIndex indexing and search."""

import pytest


def test_index_all_returns_chunk_count(rag_index):
    """index_all should have indexed chunks from sample data."""
    # The fixture already called index_all; verify collection has data
    count = rag_index._collection.count()
    assert count > 0


def test_search_returns_results(rag_index):
    results = rag_index.search("substring function")
    assert len(results) > 0
    assert all(hasattr(r, "snippet") for r in results)
    assert all(hasattr(r, "score") for r in results)


def test_search_with_source_type_filter(rag_index):
    results = rag_index.search("date format", source_type="functions_doc")
    assert len(results) > 0
    for r in results:
        assert r.source_type == "functions_doc"


def test_search_mapping_sets(rag_index):
    results = rag_index.search("order mapping", source_type="mapping_set")
    assert len(results) > 0
    for r in results:
        assert r.source_type == "mapping_set"


def test_list_files(rag_index):
    files = rag_index.list_files("format")
    assert len(files) >= 1
    assert all("file_path" in f for f in files)
    assert all("extension" in f for f in files)


def test_list_files_with_extension_filter(rag_index):
    xml_files = rag_index.list_files("format", extension="xml")
    for f in xml_files:
        assert f["extension"] == ".xml"


def test_get_file_content(rag_index):
    content = rag_index.get_file_content("formats/sample_format.xml")
    assert "Schema" in content
    assert "order_id" in content


def test_get_file_content_path_traversal(rag_index):
    with pytest.raises(ValueError, match="outside data root"):
        rag_index.get_file_content("../../etc/passwd")


def test_get_file_content_not_found(rag_index):
    with pytest.raises(FileNotFoundError):
        rag_index.get_file_content("formats/nonexistent.xml")


def test_search_top_k(rag_index):
    results = rag_index.search("function", top_k=2)
    assert len(results) <= 2


def test_empty_data_dir(tmp_path):
    """Indexing an empty data dir should return 0 and not crash."""
    from config import Settings
    from rag_index import RAGIndex

    for sub in ("formats", "mapping_sets", "functions_docs"):
        (tmp_path / sub).mkdir()
    s = Settings(
        data_root_dir=str(tmp_path),
        vector_store_dir=str(tmp_path / "vector_store"),
    )
    index = RAGIndex(s)
    count = index.index_all()
    assert count == 0
