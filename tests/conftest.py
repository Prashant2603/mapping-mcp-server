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
        '  <Field name="order_id" type="string"/>\n'
        '  <Field name="date" type="date"/>\n'
        "</Schema>"
    )

    # Sample format file (CSV)
    (formats / "products.csv").write_text(
        "product_id,name,price\n" "1,Widget,9.99\n" "2,Gadget,19.99\n"
    )

    # Sample mapping set — uses child elements for source/target (matches real data)
    (mapping_sets / "sample_mapping.xml").write_text(
        '<?xml version="1.0"?>\n'
        "<mappingSet>\n"
        "  <id>FormatA_to_FormatB</id>\n"
        "  <sourceFormat>FormatA</sourceFormat>\n"
        "  <targetFormat>FormatB</targetFormat>\n"
        "  <description>Sample mapping from FormatA to FormatB</description>\n"
        "  <mapping>\n"
        "    <description>Map order ID</description>\n"
        "    <target>/purchase/order_number</target>\n"
        '    <function>substring</function>\n'
        "    <parameter>input=$source, start=0, length=10</parameter>\n"
        "  </mapping>\n"
        "  <mapping>\n"
        "    <description>Map order date</description>\n"
        "    <target>/purchase/date</target>\n"
        '    <function>formatDate</function>\n'
        "    <parameter>input=$source, inputFormat=YYYYMMDD, outputFormat=MM/DD/YYYY</parameter>\n"
        "  </mapping>\n"
        "</mappingSet>"
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
        index.index_all(incremental=False)
        yield index
