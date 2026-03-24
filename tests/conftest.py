"""Shared test fixtures."""

import os
import tempfile

import pytest

from config import Settings
from rag_index import RAGIndex


@pytest.fixture()
def data_dir(tmp_path):
    """Create a temporary data directory with sample files."""
    formats = tmp_path / "formats"
    mapping_sets = tmp_path / "mapping_sets"
    functions_docs = tmp_path / "functions_docs"
    formats.mkdir()
    mapping_sets.mkdir()
    functions_docs.mkdir()

    # Sample format file (XML)
    (formats / "sample_format.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<Schema name="SampleFormat" type="input">\n'
        "  <Field name=\"order_id\" type=\"string\"/>\n"
        "  <Field name=\"date\" type=\"date\"/>\n"
        "</Schema>"
    )

    # Sample format file (CSV)
    (formats / "products.csv").write_text(
        "product_id,name,price\n" "1,Widget,9.99\n" "2,Gadget,19.99\n"
    )

    # Sample mapping set
    (mapping_sets / "sample_mapping.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<MappingSet name="SampleMapping" source="FormatA" target="FormatB" version="1.0">\n'
        '  <MappingRule source_path="/order/id" target_path="/purchase/order_number">\n'
        '    <Function name="substring" params="input=$source, start=0, length=10"/>\n'
        "  </MappingRule>\n"
        '  <MappingRule source_path="/order/date" target_path="/purchase/date">\n'
        '    <Function name="formatDate" params="input=$source, inputFormat=YYYYMMDD, outputFormat=MM/DD/YYYY"/>\n'
        "  </MappingRule>\n"
        "</MappingSet>"
    )

    # Sample function docs
    (functions_docs / "string_functions.md").write_text(
        "# String Functions\n\n"
        "## concat\n"
        "Concatenates two or more strings.\n"
        "**Parameters:** `value1: string, value2: string`\n"
        "**Returns:** string\n\n"
        "## substring\n"
        "Extracts a substring from a string.\n"
        "**Parameters:** `input: string, start: int, length: int`\n"
        "**Returns:** string\n"
    )

    (functions_docs / "date_functions.md").write_text(
        "# Date Functions\n\n"
        "## formatDate\n"
        "Converts a date string from one format to another.\n"
        "**Parameters:** `input: string, inputFormat: string, outputFormat: string`\n"
        "**Returns:** string\n"
    )

    return tmp_path


@pytest.fixture()
def rag_index(data_dir):
    """Create a RAGIndex with ephemeral ChromaDB over the sample data."""
    with tempfile.TemporaryDirectory() as vector_dir:
        s = Settings(
            data_root_dir=str(data_dir),
            vector_store_dir=vector_dir,
            collection_name="test_collection",
        )
        index = RAGIndex(s)
        index.index_all()
        yield index
