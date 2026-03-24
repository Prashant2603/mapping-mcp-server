"""RAG indexing and retrieval logic using ChromaDB."""

import csv
import hashlib
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

from config import SUBFOLDER_MAP, Settings
from models import SearchResult

logger = logging.getLogger(__name__)


class RAGIndex:
    """Indexes files into ChromaDB and provides semantic search."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.data_root = Path(settings.data_root_dir).resolve()
        self._client = chromadb.PersistentClient(path=settings.vector_store_dir)
        self._ef = SentenceTransformerEmbeddingFunction(
            model_name=settings.embedding_model
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.collection_name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    def index_all(self) -> int:
        """Scan data directories, chunk files, and upsert into ChromaDB.

        Returns the total number of chunks indexed.
        """
        files = self._scan_files()
        if not files:
            logger.warning("No files found to index in %s", self.data_root)
            return 0

        all_ids: list[str] = []
        all_docs: list[str] = []
        all_metas: list[dict] = []

        for file_path, source_type in files:
            chunks = self._chunk_file(file_path, source_type)
            for doc, meta in chunks:
                chunk_id = hashlib.sha256(
                    f"{meta['file_path']}::{meta['chunk_index']}".encode()
                ).hexdigest()[:16]
                all_ids.append(chunk_id)
                all_docs.append(doc)
                all_metas.append(meta)

        # Upsert in batches of 100
        batch_size = 100
        for i in range(0, len(all_ids), batch_size):
            end = i + batch_size
            self._collection.upsert(
                ids=all_ids[i:end],
                documents=all_docs[i:end],
                metadatas=all_metas[i:end],
            )

        logger.info("Indexed %d chunks from %d files", len(all_ids), len(files))
        return len(all_ids)

    def search(
        self,
        query: str,
        source_type: str | None = None,
        top_k: int | None = None,
    ) -> list[SearchResult]:
        """Semantic search over indexed content.

        Args:
            query: Natural language search query.
            source_type: Optional filter (format, mapping_set, functions_doc).
            top_k: Number of results to return.
        """
        if top_k is None:
            top_k = self.settings.default_top_k

        where = {"source_type": source_type} if source_type else None
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

    # -- Private helpers --

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

    def _chunk_markdown(
        self, content: str, base_meta: dict
    ) -> list[tuple[str, dict]]:
        """Chunk markdown by ## headers, then by paragraphs if too large."""
        sections = re.split(r"\n(?=## )", content)
        chunks: list[tuple[str, dict]] = []
        idx = 0

        for section in sections:
            section = section.strip()
            if not section:
                continue
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
