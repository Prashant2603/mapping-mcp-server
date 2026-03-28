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
    # Top-level heading should be prepended to ## sections
    assert "# Title" in chunks[1][0]
    assert "# Title" in chunks[2][0]


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


def test_chunk_mapping_set_xml(tmp_path):
    index = _make_index(tmp_path)
    # Use larger chunk size for this test to avoid excessive splitting
    index.settings.chunk_max_chars = 2000
    xml_content = (
        '<?xml version="1.0"?>\n'
        "<mappingSet>\n"
        "  <id>TestMapping_001</id>\n"
        "  <sourceFormat>FormatA</sourceFormat>\n"
        "  <targetFormat>FormatB</targetFormat>\n"
        "  <description>Test mapping</description>\n"
        "  <mapping>\n"
        "    <description>Map field X</description>\n"
        "    <target>/output/fieldX</target>\n"
        "    <function>copy</function>\n"
        "    <parameter>input=$source</parameter>\n"
        "  </mapping>\n"
        "  <mapping>\n"
        "    <description>Map field Y</description>\n"
        "    <target>/output/fieldY</target>\n"
        "    <function>concat</function>\n"
        "    <parameter>val1=$a, val2=$b</parameter>\n"
        "  </mapping>\n"
        "</mappingSet>"
    )
    meta = {"file_path": "mapping_sets/test.xml", "source_type": "mapping_set", "extension": ".xml"}
    chunks = index._chunk_mapping_set_xml(xml_content, meta)

    # Should have: summary chunk + metadata chunk + mapping rules chunk
    assert len(chunks) >= 2

    # All chunks should have enriched metadata
    for _, chunk_meta in chunks:
        assert chunk_meta["source_format"] == "FormatA"
        assert chunk_meta["target_format"] == "FormatB"

    # Summary chunk should exist with overview of rules
    summary_chunks = [(t, m) for t, m in chunks if m.get("is_summary") == "true"]
    assert len(summary_chunks) >= 1
    summary_text = summary_chunks[0][0]
    assert "FormatA" in summary_text
    assert "FormatB" in summary_text
    assert "copy" in summary_text
    assert "concat" in summary_text


def test_chunk_mapping_set_xml_groups_rules(tmp_path):
    index = _make_index(tmp_path)
    index.settings.chunk_max_chars = 5000
    # Create a mapping set with 12 rules to test grouping (should be 3 groups of 5+5+2)
    rules = ""
    for i in range(12):
        rules += (
            f"  <mapping>\n"
            f"    <description>Map field {i}</description>\n"
            f"    <target>/output/field{i}</target>\n"
            f"    <function>copy</function>\n"
            f"    <parameter>input=$source{i}</parameter>\n"
            f"  </mapping>\n"
        )
    xml_content = (
        "<mappingSet>\n"
        "  <sourceFormat>X</sourceFormat>\n"
        "  <targetFormat>Y</targetFormat>\n"
        f"{rules}"
        "</mappingSet>"
    )
    meta = {"file_path": "mapping_sets/big.xml", "source_type": "mapping_set", "extension": ".xml"}
    chunks = index._chunk_mapping_set_xml(xml_content, meta)

    # Should have summary + metadata + 3 rule groups (5+5+2)
    rule_chunks = [(t, m) for t, m in chunks if m.get("is_summary") != "true" and "mapping_functions" in m]
    assert len(rule_chunks) == 3  # ceil(12/5) = 3 groups
