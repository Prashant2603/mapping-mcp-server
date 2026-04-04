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


def test_file_index_built_on_index(rag_index):
    """File index should be populated after indexing."""
    assert len(rag_index._file_index) > 0
    # Every entry should have required keys
    for entry in rag_index._file_index.values():
        assert "source_type" in entry
        assert "name" in entry
        assert "file_path" in entry
        assert "extension" in entry


def test_file_index_mapping_set_metadata(rag_index):
    """Mapping set entries should have source/target format in the index."""
    ms_entries = rag_index.lookup(source_type="mapping_set")
    assert len(ms_entries) >= 1
    for e in ms_entries:
        assert "source_format" in e
        assert "target_format" in e


def test_lookup_by_source_format(rag_index):
    """lookup should find mapping sets by source format."""
    results = rag_index.lookup(source_format="FormatA")
    assert len(results) >= 1
    assert all("FormatA" in r.get("source_format", "") for r in results)


def test_lookup_by_target_format(rag_index):
    """lookup should find mapping sets by target format."""
    results = rag_index.lookup(target_format="FormatB")
    assert len(results) >= 1
    assert all("FormatB" in r.get("target_format", "") for r in results)


def test_lookup_case_insensitive(rag_index):
    """lookup string matching should be case-insensitive."""
    results = rag_index.lookup(source_format="formata")
    assert len(results) >= 1


def test_lookup_no_match(rag_index):
    """lookup with non-existent format should return empty."""
    results = rag_index.lookup(source_format="NonExistentFormat999")
    assert len(results) == 0


def test_file_index_persists(data_dir, tmp_path):
    """File index should persist to disk and reload."""
    import tempfile
    from config import Settings
    from rag_index import RAGIndex

    vector_dir = str(tmp_path / "vector_store")
    s = Settings(
        data_root_dir=str(data_dir),
        vector_store_dir=vector_dir,
        collection_name="test_persist",
    )
    index1 = RAGIndex(s)
    index1.index_all(incremental=False)
    assert len(index1._file_index) > 0

    # Create a new RAGIndex instance — should load the persisted index
    index2 = RAGIndex(s)
    assert index2._file_index == index1._file_index


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
