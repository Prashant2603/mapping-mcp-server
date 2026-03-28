"""RAG indexing and retrieval logic using ChromaDB."""

import csv
import hashlib
import io
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from config import SUBFOLDER_MAP, Settings
from models import SearchResult

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "file_manifest.json"


class RAGIndex:
    """Indexes files into ChromaDB and provides semantic search."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.data_root = Path(settings.data_root_dir).resolve()
        self._vector_store_dir = Path(settings.vector_store_dir)
        self._client = chromadb.PersistentClient(path=settings.vector_store_dir)
        self._ef = SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.collection_name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    def collection_count(self) -> int:
        """Return the number of chunks in the vector store."""
        return self._collection.count()

    def reset_collection(self) -> None:
        """Delete and recreate the collection."""
        self._client.delete_collection(self.settings.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.settings.collection_name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )
        # Clear the manifest
        self._save_manifest({})

    def index_all(self, incremental: bool = True) -> int:
        """Scan data directories, chunk files, and upsert into ChromaDB.

        Args:
            incremental: If True, only process new/changed files based on
                SHA-256 manifest. If False, index everything.

        Returns the total number of chunks indexed (new/changed only).
        """
        files = self._scan_files()
        if not files:
            logger.warning("No files found to index in %s", self.data_root)
            return 0

        if incremental:
            return self._index_incremental(files)
        else:
            return self._index_full(files)

    def search(
        self,
        query: str,
        source_type: str | None = None,
        top_k: int | None = None,
        where_filter: dict | None = None,
    ) -> list[SearchResult]:
        """Semantic search over indexed content.

        Args:
            query: Natural language search query.
            source_type: Optional filter (format, mapping_set, functions_doc).
            top_k: Number of results to return.
            where_filter: Optional additional ChromaDB where clause.
        """
        if top_k is None:
            top_k = self.settings.default_top_k

        where = where_filter
        if source_type and not where_filter:
            where = {"source_type": source_type}
        elif source_type and where_filter:
            where = {"$and": [{"source_type": source_type}, where_filter]}

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error("Search failed: %s", e)
            return []

        search_results: list[SearchResult] = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                search_results.append(
                    SearchResult(
                        source_type=meta["source_type"],
                        file_path=meta["file_path"],
                        snippet=doc,
                        score=round(1.0 - dist, 4),  # cosine distance to similarity
                    )
                )
        return search_results

    def list_files(
        self,
        source_type: str,
        extension: str | None = None,
    ) -> list[dict]:
        """List unique files of a given source type.

        Returns list of dicts with name, file_path, extension keys.
        """
        where: dict = {"source_type": source_type}
        if extension:
            ext = extension if extension.startswith(".") else f".{extension}"
            where = {"$and": [{"source_type": source_type}, {"extension": ext}]}

        try:
            results = self._collection.get(where=where, include=["metadatas"])
        except Exception as e:
            logger.error("list_files failed: %s", e)
            return []

        seen: set[str] = set()
        files: list[dict] = []
        for meta in results["metadatas"]:
            fp = meta["file_path"]
            if fp not in seen:
                seen.add(fp)
                files.append(
                    {
                        "name": Path(fp).stem,
                        "file_path": fp,
                        "extension": meta["extension"],
                    }
                )
        return files

    def get_file_content(self, file_path: str) -> str:
        """Read raw file content from disk with path traversal validation."""
        p = Path(file_path)
        # If relative, resolve against data_root
        resolved = (self.data_root / p).resolve() if not p.is_absolute() else p.resolve()
        if not resolved.is_relative_to(self.data_root):
            raise ValueError(
                f"Path {file_path} is outside data root {self.data_root}"
            )
        if not resolved.is_file():
            raise FileNotFoundError(f"File not found: {file_path}")
        return resolved.read_text(encoding="utf-8", errors="replace")

    # -- Incremental indexing helpers --

    def _manifest_path(self) -> Path:
        return self._vector_store_dir / MANIFEST_FILENAME

    def _load_manifest(self) -> dict:
        """Load the file manifest from disk."""
        p = self._manifest_path()
        if p.is_file():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt manifest, treating as empty")
        return {}

    def _save_manifest(self, manifest: dict) -> None:
        """Save the file manifest to disk."""
        self._vector_store_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path().write_text(json.dumps(manifest, indent=2))

    @staticmethod
    def _file_hash(path: Path) -> str:
        """Compute SHA-256 of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                h.update(block)
        return h.hexdigest()

    def _delete_chunks_for_file(self, rel_path: str) -> None:
        """Delete all chunks belonging to a file from ChromaDB."""
        try:
            self._collection.delete(where={"file_path": rel_path})
        except Exception as e:
            logger.warning("Could not delete chunks for %s: %s", rel_path, e)

    def _index_incremental(self, files: list[tuple[Path, str]]) -> int:
        """Index only new/changed files, remove deleted files."""
        manifest = self._load_manifest()
        current_files: dict[str, tuple[Path, str]] = {}

        # Compute hashes and classify files
        new_files: list[tuple[Path, str]] = []
        changed_files: list[tuple[Path, str]] = []
        unchanged_count = 0

        for file_path, source_type in files:
            rel_path = str(file_path.relative_to(self.data_root))
            current_files[rel_path] = (file_path, source_type)
            file_hash = self._file_hash(file_path)

            if rel_path not in manifest:
                new_files.append((file_path, source_type))
            elif manifest[rel_path]["sha256"] != file_hash:
                changed_files.append((file_path, source_type))
            else:
                unchanged_count += 1

        # Detect removed files
        removed = set(manifest.keys()) - set(current_files.keys())

        logger.info(
            "Scanning files... %d found (%d new, %d changed, %d unchanged, %d removed)",
            len(files), len(new_files), len(changed_files), unchanged_count, len(removed),
        )

        # Delete chunks for changed and removed files
        for rel_path in removed:
            logger.info("Removing chunks for deleted file: %s", rel_path)
            self._delete_chunks_for_file(rel_path)

        for file_path, source_type in changed_files:
            rel_path = str(file_path.relative_to(self.data_root))
            logger.info("Removing old chunks for changed file: %s", rel_path)
            self._delete_chunks_for_file(rel_path)

        # Chunk new and changed files
        to_process = new_files + changed_files
        if not to_process:
            logger.info("No files to index, everything up to date")
            # Still update manifest to remove deleted entries
            new_manifest = {k: v for k, v in manifest.items() if k not in removed}
            self._save_manifest(new_manifest)
            return 0

        all_ids, all_docs, all_metas = self._chunk_files_with_logging(to_process)

        # Pre-compute embeddings in one batch
        if all_docs:
            self._embed_and_upsert(all_ids, all_docs, all_metas)

        # Update manifest
        new_manifest = {k: v for k, v in manifest.items() if k not in removed}
        for file_path, source_type in to_process:
            rel_path = str(file_path.relative_to(self.data_root))
            chunk_count = sum(1 for m in all_metas if m["file_path"] == rel_path)
            new_manifest[rel_path] = {
                "sha256": self._file_hash(file_path),
                "chunk_count": chunk_count,
            }
        self._save_manifest(new_manifest)

        logger.info("Indexed %d chunks from %d files", len(all_ids), len(to_process))
        return len(all_ids)

    def _index_full(self, files: list[tuple[Path, str]]) -> int:
        """Index all files from scratch."""
        logger.info("Full index: processing %d files", len(files))
        all_ids, all_docs, all_metas = self._chunk_files_with_logging(files)

        if all_docs:
            self._embed_and_upsert(all_ids, all_docs, all_metas)

        # Build fresh manifest
        manifest: dict = {}
        for file_path, source_type in files:
            rel_path = str(file_path.relative_to(self.data_root))
            chunk_count = sum(1 for m in all_metas if m["file_path"] == rel_path)
            manifest[rel_path] = {
                "sha256": self._file_hash(file_path),
                "chunk_count": chunk_count,
            }
        self._save_manifest(manifest)

        logger.info("Indexed %d chunks from %d files", len(all_ids), len(files))
        return len(all_ids)

    def _chunk_files_with_logging(
        self, files: list[tuple[Path, str]]
    ) -> tuple[list[str], list[str], list[dict]]:
        """Chunk a list of files with per-file progress logging."""
        all_ids: list[str] = []
        all_docs: list[str] = []
        all_metas: list[dict] = []

        for i, (file_path, source_type) in enumerate(files, 1):
            chunks = self._chunk_file(file_path, source_type)
            logger.info(
                "Chunking file %d/%d: %s (%d chunks)",
                i, len(files), file_path.name, len(chunks),
            )
            for doc, meta in chunks:
                chunk_id = hashlib.sha256(
                    f"{meta['file_path']}::{meta['chunk_index']}".encode()
                ).hexdigest()[:16]
                all_ids.append(chunk_id)
                all_docs.append(doc)
                all_metas.append(meta)

        return all_ids, all_docs, all_metas

    def _embed_and_upsert(
        self,
        all_ids: list[str],
        all_docs: list[str],
        all_metas: list[dict],
    ) -> None:
        """Pre-compute embeddings in one batch, then upsert to ChromaDB."""
        logger.info("Computing embeddings for %d chunks...", len(all_docs))
        t0 = time.time()
        all_embeddings = self._ef(all_docs)
        elapsed = time.time() - t0
        logger.info("Embeddings computed in %.1fs", elapsed)

        batch_size = 100
        total_batches = (len(all_ids) + batch_size - 1) // batch_size
        for i in range(0, len(all_ids), batch_size):
            end = i + batch_size
            batch_num = i // batch_size + 1
            logger.info("Upserting batch %d/%d...", batch_num, total_batches)
            self._collection.upsert(
                ids=all_ids[i:end],
                documents=all_docs[i:end],
                metadatas=all_metas[i:end],
                embeddings=all_embeddings[i:end],
            )

    # -- File scanning and chunking --

    def _scan_files(self) -> list[tuple[Path, str]]:
        """Walk the 3 subfolders and return (path, source_type) pairs."""
        files: list[tuple[Path, str]] = []
        for subfolder, source_type in SUBFOLDER_MAP.items():
            folder = self.data_root / subfolder
            if not folder.is_dir():
                logger.warning("Subfolder not found: %s", folder)
                continue
            for path in folder.rglob("*"):
                if path.is_file():
                    files.append((path, source_type))
        return files

    def _chunk_file(
        self, file_path: Path, source_type: str
    ) -> list[tuple[str, dict]]:
        """Read and chunk a file based on its extension."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.warning("Could not read %s: %s", file_path, e)
            return []

        if not content.strip():
            return []

        ext = file_path.suffix.lower()
        rel_path = str(file_path.relative_to(self.data_root))
        base_meta = {
            "file_path": rel_path,
            "source_type": source_type,
            "extension": ext,
        }

        if ext == ".xml":
            if source_type == "mapping_set":
                return self._chunk_mapping_set_xml(content, base_meta)
            return self._chunk_xml(content, base_meta)
        elif ext in (".md", ".txt"):
            return self._chunk_markdown(content, base_meta)
        elif ext == ".csv":
            return self._chunk_csv(content, base_meta)
        elif ext == ".json":
            return self._chunk_json(content, base_meta)
        else:
            return self._chunk_plain(content, base_meta)

    def _chunk_xml(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Chunk XML by top-level child elements."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            logger.warning("Malformed XML in %s, falling back to plain", base_meta["file_path"])
            return self._chunk_plain(content, base_meta)

        children = list(root)
        if not children:
            return [(content, {**base_meta, "chunk_index": 0})]

        chunks: list[tuple[str, dict]] = []
        root_tag = root.tag
        root_attribs = " ".join(f'{k}="{v}"' for k, v in root.attrib.items())
        context_prefix = f"<!-- Root: <{root_tag} {root_attribs}> -->\n" if root_attribs else f"<!-- Root: <{root_tag}> -->\n"

        idx = 0
        for child in children:
            child_str = ET.tostring(child, encoding="unicode")
            chunk_text = context_prefix + child_str
            # Sub-chunk oversized XML children using plain text splitting
            if len(chunk_text) > self.settings.chunk_max_chars:
                for sub_chunk in self._split_text(chunk_text):
                    chunks.append((sub_chunk, {**base_meta, "chunk_index": idx}))
                    idx += 1
            else:
                chunks.append((chunk_text, {**base_meta, "chunk_index": idx}))
                idx += 1

        return chunks

    def _chunk_mapping_set_xml(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Chunk mapping set XML with enriched context headers and grouped rules."""
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            logger.warning("Malformed XML in %s, falling back to plain", base_meta["file_path"])
            return self._chunk_plain(content, base_meta)

        children = list(root)
        if not children:
            return [(content, {**base_meta, "chunk_index": 0})]

        # Extract mapping set metadata from child elements
        source_format = ""
        target_format = ""
        ms_id = ""
        ms_description = ""
        mapping_rules: list[ET.Element] = []
        metadata_elements: list[ET.Element] = []

        for child in children:
            tag = child.tag.lower() if child.tag else ""
            if tag == "sourceformat":
                source_format = (child.text or "").strip()
                metadata_elements.append(child)
            elif tag == "targetformat":
                target_format = (child.text or "").strip()
                metadata_elements.append(child)
            elif tag == "id":
                ms_id = (child.text or "").strip()
                metadata_elements.append(child)
            elif tag == "description":
                ms_description = (child.text or "").strip()
                metadata_elements.append(child)
            elif tag == "mapping":
                mapping_rules.append(child)
            else:
                metadata_elements.append(child)

        # Also check root attributes as fallback
        if not source_format:
            source_format = root.attrib.get("source", "")
        if not target_format:
            target_format = root.attrib.get("target", "")
        if not ms_id:
            ms_id = root.attrib.get("name", "")

        # Build enriched context header
        header_lines = []
        if ms_id:
            header_lines.append(f"Mapping Set: {ms_id}")
        if source_format or target_format:
            header_lines.append(f"Source: {source_format} | Target: {target_format}")
        if ms_description:
            header_lines.append(f"Description: {ms_description}")
        header = "\n".join(f"<!-- {line} -->" for line in header_lines) + "\n" if header_lines else ""

        # Enriched metadata for all chunks from this file
        enriched_meta = {
            **base_meta,
            "source_format": source_format,
            "target_format": target_format,
        }

        chunks: list[tuple[str, dict]] = []
        idx = 0

        # Chunk 0: Summary chunk — header + one-liner per mapping rule
        summary_lines = list(header_lines)
        summary_lines.append(f"Total mapping rules: {len(mapping_rules)}")
        summary_lines.append("")
        for rule in mapping_rules:
            target_el = rule.find("target")
            func_el = rule.find("function")
            desc_el = rule.find("description")
            target_val = (target_el.text or "").strip() if target_el is not None else ""
            func_val = (func_el.text or "").strip() if func_el is not None else ""
            desc_val = (desc_el.text or "").strip() if desc_el is not None else ""
            if desc_val and len(desc_val) > 80:
                desc_val = desc_val[:77] + "..."
            line = f"  {target_val} -> {func_val}"
            if desc_val:
                line += f" ({desc_val})"
            summary_lines.append(line)

        summary_text = "\n".join(summary_lines)
        # Sub-chunk if summary is too large
        if len(summary_text) <= self.settings.chunk_max_chars:
            chunks.append((summary_text, {**enriched_meta, "chunk_index": idx, "is_summary": "true"}))
            idx += 1
        else:
            for sub_chunk in self._split_text(summary_text):
                chunks.append((sub_chunk, {**enriched_meta, "chunk_index": idx, "is_summary": "true"}))
                idx += 1

        # Chunk metadata elements together
        if metadata_elements:
            meta_strs = [ET.tostring(el, encoding="unicode") for el in metadata_elements]
            meta_text = header + "\n".join(meta_strs)
            if len(meta_text) <= self.settings.chunk_max_chars:
                chunks.append((meta_text, {**enriched_meta, "chunk_index": idx}))
                idx += 1
            else:
                for sub_chunk in self._split_text(meta_text):
                    chunks.append((sub_chunk, {**enriched_meta, "chunk_index": idx}))
                    idx += 1

        # Group mapping rules in batches of 5
        group_size = 5
        for i in range(0, len(mapping_rules), group_size):
            group = mapping_rules[i : i + group_size]
            rule_strs = [ET.tostring(rule, encoding="unicode") for rule in group]
            chunk_text = header + "\n".join(rule_strs)

            # Extract function names for metadata
            func_names = []
            for rule in group:
                func_el = rule.find("function")
                if func_el is not None and func_el.text:
                    func_names.append(func_el.text.strip())

            group_meta = {
                **enriched_meta,
                "chunk_index": idx,
                "mapping_functions": ", ".join(func_names) if func_names else "",
            }

            if len(chunk_text) <= self.settings.chunk_max_chars:
                chunks.append((chunk_text, group_meta))
                idx += 1
            else:
                for sub_chunk in self._split_text(chunk_text):
                    chunks.append((sub_chunk, {**group_meta, "chunk_index": idx}))
                    idx += 1

        return chunks

    def _chunk_markdown(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Chunk markdown by ## headers, then by paragraphs if too large.

        Prepends the top-level # heading to each ## section for context.
        """
        # Extract top-level heading if present
        top_heading = ""
        match = re.match(r"^(# .+?)(?:\n|$)", content)
        if match:
            top_heading = match.group(1).strip()

        sections = re.split(r"\n(?=## )", content)
        chunks: list[tuple[str, dict]] = []
        idx = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Prepend top-level heading if this section doesn't start with it
            if top_heading and not section.startswith("# "):
                section = top_heading + "\n\n" + section

            if len(section) <= self.settings.chunk_max_chars:
                chunks.append((section, {**base_meta, "chunk_index": idx}))
                idx += 1
            else:
                paragraphs = section.split("\n\n")
                current = ""
                for para in paragraphs:
                    if len(current) + len(para) + 2 > self.settings.chunk_max_chars and current:
                        chunks.append((current.strip(), {**base_meta, "chunk_index": idx}))
                        idx += 1
                        current = para
                    else:
                        current = current + "\n\n" + para if current else para
                if current.strip():
                    chunks.append((current.strip(), {**base_meta, "chunk_index": idx}))
                    idx += 1

        return chunks if chunks else [(content, {**base_meta, "chunk_index": 0})]

    def _chunk_csv(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Chunk CSV by groups of rows, preserving header."""
        if len(content) <= self.settings.chunk_max_chars:
            return [(content, {**base_meta, "chunk_index": 0})]

        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return [(content, {**base_meta, "chunk_index": 0})]

        header = rows[0]
        data_rows = rows[1:]
        group_size = 20
        chunks: list[tuple[str, dict]] = []

        for i in range(0, len(data_rows), group_size):
            group = data_rows[i : i + group_size]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(header)
            writer.writerows(group)
            chunks.append((buf.getvalue(), {**base_meta, "chunk_index": len(chunks)}))

        return chunks if chunks else [(content, {**base_meta, "chunk_index": 0})]

    def _chunk_json(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Chunk JSON arrays by groups of records."""
        if len(content) <= self.settings.chunk_max_chars:
            return [(content, {**base_meta, "chunk_index": 0})]

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return self._chunk_plain(content, base_meta)

        if isinstance(data, list) and len(data) > 1:
            group_size = 10
            chunks: list[tuple[str, dict]] = []
            for i in range(0, len(data), group_size):
                group = data[i : i + group_size]
                chunk_text = json.dumps(group, indent=2)
                chunks.append((chunk_text, {**base_meta, "chunk_index": len(chunks)}))
            return chunks

        return [(content, {**base_meta, "chunk_index": 0})]

    def _split_text(self, text: str) -> list[str]:
        """Split text into chunks of max_chars, preferring newline boundaries."""
        max_chars = self.settings.chunk_max_chars
        if len(text) <= max_chars:
            return [text]

        parts: list[str] = []
        start = 0
        while start < len(text):
            end = start + max_chars
            if end >= len(text):
                parts.append(text[start:])
                break
            # Try to break at a newline
            nl = text.rfind("\n", start, end)
            if nl > start:
                end = nl + 1
            parts.append(text[start:end])
            start = end
        return parts

    def _chunk_plain(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Fallback: chunk by max char size."""
        if len(content) <= self.settings.chunk_max_chars:
            return [(content, {**base_meta, "chunk_index": 0})]

        chunks: list[tuple[str, dict]] = []
        for part in self._split_text(content):
            chunks.append((part, {**base_meta, "chunk_index": len(chunks)}))

        return chunks
