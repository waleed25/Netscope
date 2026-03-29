"""
Tests for rag.ingest — unit tests that mock ChromaDB and embedding calls
so no GPU/model download is needed.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock


# ── IngestResult ──────────────────────────────────────────────────────────────

class TestIngestResult:
    def test_fields_accessible(self):
        from rag.ingest import IngestResult
        r = IngestResult(source_name="test", chunk_count=5, skipped=1, duration_s=0.5)
        assert r.source_name == "test"
        assert r.chunk_count == 5
        assert r.skipped == 1
        assert r.duration_s == 0.5

    def test_error_defaults_empty(self):
        from rag.ingest import IngestResult
        r = IngestResult(source_name="x", chunk_count=0, skipped=0, duration_s=0.0)
        assert r.error == ""

    def test_cancelled_defaults_false(self):
        from rag.ingest import IngestResult
        r = IngestResult(source_name="x", chunk_count=0, skipped=0, duration_s=0.0)
        assert r.cancelled is False

    def test_with_error(self):
        from rag.ingest import IngestResult
        r = IngestResult(source_name="x", chunk_count=0, skipped=0, duration_s=0.0, error="bad input")
        assert r.error == "bad input"


# ── get_collection singleton ──────────────────────────────────────────────────

class TestGetCollection:
    def test_returns_same_instance_on_second_call(self):
        """get_collection should be idempotent (returns cached singleton)."""
        import rag.ingest as ingest_mod

        mock_col = MagicMock()
        original = ingest_mod._collection

        try:
            ingest_mod._collection = mock_col
            result1 = ingest_mod.get_collection()
            result2 = ingest_mod.get_collection()
            assert result1 is mock_col
            assert result2 is mock_col
        finally:
            ingest_mod._collection = original

    @patch("chromadb.PersistentClient")
    def test_creates_collection_with_cosine_space(self, mock_client_cls):
        import rag.ingest as ingest_mod

        original_col = ingest_mod._collection
        original_cli = ingest_mod._chroma_client
        ingest_mod._collection = None
        ingest_mod._chroma_client = None

        mock_client = MagicMock()
        mock_col = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.get_or_create_collection.return_value = mock_col

        try:
            result = ingest_mod.get_collection()
            assert result is mock_col
            mock_client.get_or_create_collection.assert_called_once()
            call_kwargs = mock_client.get_or_create_collection.call_args[1]
            assert call_kwargs.get("metadata", {}).get("hnsw:space") == "cosine"
        finally:
            ingest_mod._collection = original_col
            ingest_mod._chroma_client = original_cli


# ── BM25 index helpers ────────────────────────────────────────────────────────

class TestBm25Rebuild:
    def test_rebuild_with_empty_corpus_produces_none(self):
        import rag.ingest as ingest_mod

        original_bm25   = ingest_mod._bm25
        original_corpus = ingest_mod._bm25_corpus[:]

        ingest_mod._bm25_corpus = []
        ingest_mod._bm25 = None

        try:
            ingest_mod._rebuild_bm25_index()
            assert ingest_mod._bm25 is None
        finally:
            ingest_mod._bm25        = original_bm25
            ingest_mod._bm25_corpus = original_corpus

    def test_rebuild_with_corpus_creates_bm25(self):
        import rag.ingest as ingest_mod

        original_bm25   = ingest_mod._bm25
        original_corpus = ingest_mod._bm25_corpus[:]

        ingest_mod._bm25_corpus = [
            "wireshark display filter tcp",
            "bpf capture filter udp port 53",
            "modbus function code read holding registers",
        ]

        try:
            ingest_mod._rebuild_bm25_index()
            assert ingest_mod._bm25 is not None
            scores = ingest_mod._bm25.get_scores(["modbus"])
            assert len(scores) == 3
            assert scores[2] >= scores[0]
        except ImportError:
            pytest.skip("rank_bm25 not installed")
        finally:
            ingest_mod._bm25        = original_bm25
            ingest_mod._bm25_corpus = original_corpus
