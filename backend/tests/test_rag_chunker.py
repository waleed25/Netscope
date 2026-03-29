"""
Tests for rag.chunker — sentence splitting and window building.
No external dependencies required.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from rag.chunker import split_sentences, build_windows, chunk_text, ChunkRecord, MAX_CHUNK_CHARS


# ── split_sentences ────────────────────────────────────────────────────────────

class TestSplitSentences:
    def test_empty_string(self):
        assert split_sentences("") == []

    def test_whitespace_only(self):
        assert split_sentences("   \n\t  ") == []

    def test_single_sentence(self):
        result = split_sentences("Hello world.")
        assert result == ["Hello world."]

    def test_two_sentences(self):
        result = split_sentences("First sentence. Second sentence.")
        assert len(result) == 2
        assert "First sentence." in result[0]

    def test_markdown_heading_kept_intact(self):
        result = split_sentences("# My Heading\nSome text.")
        assert result[0] == "# My Heading"

    def test_cli_command_kept_intact(self):
        result = split_sentences("show ip route\nAnother line.")
        assert result[0] == "show ip route"

    def test_code_fence_kept_intact(self):
        result = split_sentences("```python\ncode here\n```")
        # Lines starting with ``` treated as single units
        assert any(r.startswith("```") for r in result)

    def test_ip_address_not_split(self):
        result = split_sentences("Server at 192.168.1.10 is down.")
        # The IP address dot should not split the sentence
        assert len(result) == 1

    def test_table_row_kept_intact(self):
        result = split_sentences("| col1 | col2 |\n| data | val |")
        assert all(r.startswith("|") for r in result)

    def test_multiple_blank_lines_ignored(self):
        result = split_sentences("Sentence one.\n\n\nSentence two.")
        assert len(result) == 2


# ── build_windows ──────────────────────────────────────────────────────────────

class TestBuildWindows:
    def test_empty_sentences(self):
        assert build_windows([]) == []

    def test_single_sentence_no_neighbours(self):
        records = build_windows(["Only sentence."], embed_window=1, context_window=3)
        assert len(records) == 1
        assert records[0].embed_text == "Only sentence."
        assert records[0].window_text == "Only sentence."

    def test_embed_window_includes_neighbours(self):
        sentences = ["A.", "B.", "C.", "D.", "E."]
        records = build_windows(sentences, embed_window=1, context_window=2)
        # With stride = embed_window+1 = 2, anchors are at indices 0, 2, 4
        assert len(records) == 3
        # Anchor 0: embed includes sentences 0-1 (A, B)
        assert "A." in records[0].embed_text
        assert "B." in records[0].embed_text
        # Anchor 2 (C): embed includes B, C, D
        assert "B." in records[1].embed_text
        assert "C." in records[1].embed_text
        assert "D." in records[1].embed_text

    def test_context_window_wider_than_embed(self):
        sentences = ["A.", "B.", "C.", "D.", "E."]
        records = build_windows(sentences, embed_window=1, context_window=2)
        # Anchor 2 (C): context includes A-E, embed includes B-D
        r = records[1]
        assert len(r.window_text) >= len(r.embed_text)

    def test_hard_cap_applied(self):
        # Create a sentence that will produce very long window_text
        long_sentences = [f"This is sentence number {i} with some padding text." for i in range(100)]
        records = build_windows(long_sentences, embed_window=5, context_window=20)
        for r in records:
            assert len(r.window_text) <= MAX_CHUNK_CHARS + 1  # +1 for the ellipsis char

    def test_char_offset_increases(self):
        sentences = ["Short.", "Also short.", "Third.", "Fourth.", "Fifth."]
        records = build_windows(sentences)
        offsets = [r.char_offset for r in records]
        # With default embed_window=1, stride=2, anchors at 0, 2, 4
        assert len(offsets) >= 2
        for j in range(len(offsets) - 1):
            assert offsets[j] < offsets[j + 1]

    def test_sentence_idx_strided(self):
        sentences = ["A.", "B.", "C.", "D.", "E."]
        records = build_windows(sentences)
        # Default embed_window=1 -> stride=2 -> anchors at 0, 2, 4
        assert [r.sentence_idx for r in records] == [0, 2, 4]


# ── chunk_text ─────────────────────────────────────────────────────────────────

class TestChunkText:
    def test_empty_returns_empty(self):
        assert chunk_text("") == []

    def test_returns_chunk_records(self):
        result = chunk_text("Hello world. This is a test.")
        assert all(isinstance(r, ChunkRecord) for r in result)

    def test_embed_text_non_empty(self):
        result = chunk_text("Packet capture filters in Wireshark. BPF syntax used.")
        assert all(r.embed_text for r in result)

    def test_window_text_non_empty(self):
        result = chunk_text("Some text here. More text follows. End of doc.")
        assert all(r.window_text for r in result)

    def test_multiline_document(self):
        doc = (
            "# Wireshark Display Filters\n"
            "Use display filters to narrow packet view.\n"
            "Example: ip.addr == 192.168.1.1\n"
            "You can also filter by protocol.\n"
        )
        result = chunk_text(doc)
        # 4 sentences with stride 2 -> 2 chunks
        assert len(result) >= 2
