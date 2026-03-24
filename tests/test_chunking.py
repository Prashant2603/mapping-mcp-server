"""Tests for file chunking logic."""

from config import Settings
from rag_index import RAGIndex


def _make_index(tmp_path):
    """Helper to create a RAGIndex for chunking tests (no files needed)."""
    for sub in ("formats", "mapping_sets", "functions_docs"):
        (tmp_path / sub).mkdir(exist_ok=True)
    s = Settings(
        data_root_dir=str(tmp_path),
        vector_store_dir=str(tmp_path / "vector_store"),
        chunk_max_chars=200,
    )
    return RAGIndex(s)


def test_chunk_xml(tmp_path):
    index = _make_index(tmp_path)
    xml_content = (
        '<?xml version="1.0"?>\n'
        '<Root attr="val">\n'
        "  <Child1>text1</Child1>\n"
        "  <Child2>text2</Child2>\n"
        "</Root>"
    )
    meta = {"file_path": "test.xml", "source_type": "format", "extension": ".xml"}
    chunks = index._chunk_xml(xml_content, meta)
    assert len(chunks) == 2
    assert "Child1" in chunks[0][0]
    assert "Child2" in chunks[1][0]
    # Should include root context
    assert "Root" in chunks[0][0]
    assert chunks[0][1]["chunk_index"] == 0
    assert chunks[1][1]["chunk_index"] == 1


def test_chunk_xml_malformed(tmp_path):
    index = _make_index(tmp_path)
    bad_xml = "<not>valid<xml"
    meta = {"file_path": "bad.xml", "source_type": "format", "extension": ".xml"}
    chunks = index._chunk_xml(bad_xml, meta)
    # Should fall back to plain text
    assert len(chunks) >= 1
    assert "not" in chunks[0][0]


def test_chunk_markdown(tmp_path):
    index = _make_index(tmp_path)
    md = "# Title\n\nIntro text\n\n## Section A\n\nContent A\n\n## Section B\n\nContent B"
    meta = {"file_path": "test.md", "source_type": "functions_doc", "extension": ".md"}
    chunks = index._chunk_markdown(md, meta)
    assert len(chunks) == 3  # intro + section A + section B
    assert "Title" in chunks[0][0]
    assert "Section A" in chunks[1][0]
    assert "Section B" in chunks[2][0]


def test_chunk_markdown_large_section(tmp_path):
    index = _make_index(tmp_path)
    # Create a section larger than chunk_max_chars (200)
    large_section = "## Big\n\n" + "word " * 100
    meta = {"file_path": "big.md", "source_type": "functions_doc", "extension": ".md"}
    chunks = index._chunk_markdown(large_section, meta)
    assert len(chunks) >= 2


def test_chunk_csv(tmp_path):
    index = _make_index(tmp_path)
    rows = ["col1,col2"] + [f"val{i},val{i}" for i in range(50)]
    csv_content = "\n".join(rows)
    meta = {"file_path": "big.csv", "source_type": "format", "extension": ".csv"}
    chunks = index._chunk_csv(csv_content, meta)
    # 50 data rows / 20 per group = 3 chunks
    assert len(chunks) == 3
    # Each chunk should start with the header
    for chunk_text, _ in chunks:
        assert chunk_text.startswith("col1,col2")


def test_chunk_csv_small(tmp_path):
    index = _make_index(tmp_path)
    csv_content = "a,b\n1,2\n3,4"
    meta = {"file_path": "small.csv", "source_type": "format", "extension": ".csv"}
    chunks = index._chunk_csv(csv_content, meta)
    assert len(chunks) == 1


def test_chunk_json_array(tmp_path):
    index = _make_index(tmp_path)
    import json

    data = [{"id": i, "name": f"item{i}"} for i in range(25)]
    content = json.dumps(data, indent=2)
    meta = {"file_path": "big.json", "source_type": "format", "extension": ".json"}
    chunks = index._chunk_json(content, meta)
    # 25 items / 10 per group = 3 chunks
    assert len(chunks) == 3


def test_chunk_plain(tmp_path):
    index = _make_index(tmp_path)
    content = "x" * 500  # chunk_max_chars=200
    meta = {"file_path": "plain.txt", "source_type": "functions_doc", "extension": ".txt"}
    chunks = index._chunk_plain(content, meta)
    assert len(chunks) == 3  # 200 + 200 + 100
