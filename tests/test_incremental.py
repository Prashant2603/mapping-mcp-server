"""Tests for incremental indexing logic."""

import json
import tempfile

import pytest

from config import Settings
from rag_index import RAGIndex


def _make_settings(tmp_path, vector_dir):
    for sub in ("formats", "mapping_sets", "functions_docs"):
        (tmp_path / sub).mkdir(exist_ok=True)
    return Settings(
        data_root_dir=str(tmp_path),
        vector_store_dir=str(vector_dir),
        collection_name="test_incremental",
    )


def test_incremental_indexes_new_files(tmp_path):
    with tempfile.TemporaryDirectory() as vdir:
        s = _make_settings(tmp_path, vdir)

        # Write a file and do full index
        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>hello</Child></Root>'
        )
        index = RAGIndex(s)
        count1 = index.index_all(incremental=False)
        assert count1 > 0

        # Add a new file and do incremental index
        (tmp_path / "formats" / "b.xml").write_text(
            '<Root><Child>world</Child></Root>'
        )
        index2 = RAGIndex(s)
        count2 = index2.index_all(incremental=True)
        assert count2 > 0  # Only new file indexed

        # Total should be more than first run
        assert index2.collection_count() > count1


def test_incremental_skips_unchanged_files(tmp_path):
    with tempfile.TemporaryDirectory() as vdir:
        s = _make_settings(tmp_path, vdir)

        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>hello</Child></Root>'
        )
        index = RAGIndex(s)
        index.index_all(incremental=False)

        # Run incremental again with no changes
        index2 = RAGIndex(s)
        count = index2.index_all(incremental=True)
        assert count == 0  # Nothing new to index


def test_incremental_reindexes_changed_files(tmp_path):
    with tempfile.TemporaryDirectory() as vdir:
        s = _make_settings(tmp_path, vdir)

        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>hello</Child></Root>'
        )
        index = RAGIndex(s)
        index.index_all(incremental=False)
        count_before = index.collection_count()

        # Modify the file
        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>changed</Child><Child>extra</Child></Root>'
        )
        index2 = RAGIndex(s)
        count = index2.index_all(incremental=True)
        assert count > 0  # Changed file was re-indexed


def test_incremental_removes_deleted_files(tmp_path):
    with tempfile.TemporaryDirectory() as vdir:
        s = _make_settings(tmp_path, vdir)

        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>hello</Child></Root>'
        )
        (tmp_path / "formats" / "b.xml").write_text(
            '<Root><Child>world</Child></Root>'
        )
        index = RAGIndex(s)
        index.index_all(incremental=False)
        count_with_both = index.collection_count()

        # Delete one file
        (tmp_path / "formats" / "b.xml").unlink()
        index2 = RAGIndex(s)
        index2.index_all(incremental=True)
        assert index2.collection_count() < count_with_both


def test_manifest_persists(tmp_path):
    with tempfile.TemporaryDirectory() as vdir:
        s = _make_settings(tmp_path, vdir)

        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>hello</Child></Root>'
        )
        index = RAGIndex(s)
        index.index_all(incremental=False)

        # Check manifest file exists
        manifest_path = index._manifest_path()
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text())
        assert "formats/a.xml" in manifest
        assert "sha256" in manifest["formats/a.xml"]
        assert "chunk_count" in manifest["formats/a.xml"]


def test_reset_collection(tmp_path):
    with tempfile.TemporaryDirectory() as vdir:
        s = _make_settings(tmp_path, vdir)

        (tmp_path / "formats" / "a.xml").write_text(
            '<Root><Child>hello</Child></Root>'
        )
        index = RAGIndex(s)
        index.index_all(incremental=False)
        assert index.collection_count() > 0

        index.reset_collection()
        assert index.collection_count() == 0
