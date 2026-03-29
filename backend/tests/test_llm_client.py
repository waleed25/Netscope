"""
Unit tests for agent/llm_client.py

Covers:
  - get_token_usage: returns copy of current counters
  - reset_token_usage: zeroes all counters
  - _update_usage: increments counters from response usage object
  - get_client: returns correct base_url and model per backend
  - chat_completion: sends messages, returns text, updates tokens (mocked)
  - chat_completion_stream: yields tokens, updates usage (mocked)
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import agent.llm_client as llm_client
from agent.llm_client import (
    get_token_usage,
    reset_token_usage,
    _update_usage,
    get_client,
    chat_completion,
    chat_completion_stream,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fresh_counters():
    """Reset module-level counters before each test."""
    reset_token_usage()


def _make_usage(prompt=10, completion=5):
    u = MagicMock()
    u.prompt_tokens = prompt
    u.completion_tokens = completion
    u.total_tokens = prompt + completion
    return u


# ── get_token_usage / reset_token_usage ───────────────────────────────────────

class TestTokenCounters:
    def setup_method(self):
        _fresh_counters()

    def test_initial_state_all_zeros(self):
        usage = get_token_usage()
        assert usage == {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "requests": 0,
        }

    def test_returns_copy_not_reference(self):
        u1 = get_token_usage()
        u1["prompt_tokens"] = 9999
        assert get_token_usage()["prompt_tokens"] == 0

    def test_reset_zeroes_non_zero_counters(self):
        _update_usage(_make_usage(100, 50))
        assert get_token_usage()["total_tokens"] == 150
        reset_token_usage()
        assert get_token_usage()["total_tokens"] == 0

    def test_reset_zeroes_request_count(self):
        _update_usage(_make_usage(1, 1))
        _update_usage(_make_usage(1, 1))
        assert get_token_usage()["requests"] == 2
        reset_token_usage()
        assert get_token_usage()["requests"] == 0


# ── _update_usage ─────────────────────────────────────────────────────────────

class TestUpdateUsage:
    def setup_method(self):
        _fresh_counters()

    def test_increments_all_fields(self):
        _update_usage(_make_usage(10, 5))
        u = get_token_usage()
        assert u["prompt_tokens"] == 10
        assert u["completion_tokens"] == 5
        assert u["total_tokens"] == 15
        assert u["requests"] == 1

    def test_accumulates_across_multiple_calls(self):
        _update_usage(_make_usage(10, 5))
        _update_usage(_make_usage(20, 10))
        u = get_token_usage()
        assert u["prompt_tokens"] == 30
        assert u["completion_tokens"] == 15
        assert u["total_tokens"] == 45
        assert u["requests"] == 2

    def test_none_usage_object_does_not_crash(self):
        _update_usage(None)
        assert get_token_usage()["requests"] == 0

    def test_usage_with_none_fields_treated_as_zero(self):
        u = MagicMock()
        u.prompt_tokens = None
        u.completion_tokens = None
        u.total_tokens = None
        _update_usage(u)
        assert get_token_usage()["prompt_tokens"] == 0


# ── get_client ────────────────────────────────────────────────────────────────

class TestGetClient:
    def test_ollama_backend_uses_ollama_url(self):
        from config import settings
        settings.llm_backend = "ollama"
        settings.ollama_base_url = "http://localhost:11434/v1"
        settings.ollama_model = "qwen2.5:3b"

        client, model = get_client()
        assert model == "qwen2.5:3b"
        assert client.base_url is not None

    def test_lmstudio_backend_uses_lmstudio_url(self):
        from config import settings
        settings.llm_backend = "lmstudio"
        settings.lmstudio_base_url = "http://localhost:1234/v1"
        settings.lmstudio_model = "mistral-7b"

        client, model = get_client()
        assert model == "mistral-7b"

    def test_returns_tuple_of_two(self):
        result = get_client()
        assert len(result) == 2

    def teardown_method(self):
        from config import settings
        settings.llm_backend = "ollama"


# ── chat_completion (mocked) ──────────────────────────────────────────────────

class TestChatCompletion:
    def setup_method(self):
        _fresh_counters()

    @pytest.mark.asyncio
    async def test_returns_response_text(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello world"
        mock_response.usage = _make_usage(5, 3)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "get_client", return_value=(mock_client, "test-model")):
            result = await chat_completion([{"role": "user", "content": "hi"}])

        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_updates_token_usage(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hi"
        mock_response.usage = _make_usage(10, 4)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "get_client", return_value=(mock_client, "test-model")):
            await chat_completion([{"role": "user", "content": "hi"}])

        u = get_token_usage()
        assert u["prompt_tokens"] == 10
        assert u["completion_tokens"] == 4
        assert u["requests"] == 1

    @pytest.mark.asyncio
    async def test_none_content_returns_empty_string(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = None
        mock_response.usage = _make_usage(1, 0)

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(llm_client, "get_client", return_value=(mock_client, "test-model")):
            result = await chat_completion([])

        assert result == ""


# ── chat_completion_stream (mocked) ──────────────────────────────────────────

class TestChatCompletionStream:
    def setup_method(self):
        _fresh_counters()

    @pytest.mark.asyncio
    async def test_yields_tokens(self):
        def _make_chunk(content, usage=None):
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            chunk.usage = usage
            return chunk

        chunks = [
            _make_chunk("Hello"),
            _make_chunk(" world"),
            _make_chunk(None, usage=_make_usage(5, 2)),
        ]

        async def _fake_stream():
            for c in chunks:
                yield c

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_fake_stream())

        with patch.object(llm_client, "get_client", return_value=(mock_client, "test-model")):
            tokens = []
            async for token in chat_completion_stream([{"role": "user", "content": "hi"}]):
                tokens.append(token)

        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_updates_usage_from_final_chunk(self):
        def _make_chunk(content, usage=None):
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = content
            chunk.usage = usage
            return chunk

        chunks = [
            _make_chunk("hi"),
            _make_chunk(None, usage=_make_usage(8, 3)),
        ]

        async def _fake_stream():
            for c in chunks:
                yield c

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=_fake_stream())

        with patch.object(llm_client, "get_client", return_value=(mock_client, "test-model")):
            async for _ in chat_completion_stream([]):
                pass

        u = get_token_usage()
        assert u["prompt_tokens"] == 8
        assert u["completion_tokens"] == 3
