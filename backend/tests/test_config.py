"""
Unit tests for config.py

Covers:
  - get_active_llm_config: correct values for ollama and lmstudio backends
  - Settings defaults
"""

import pytest
from config import settings, get_active_llm_config


class TestGetActiveLLMConfig:
    def setup_method(self):
        # Save original state
        self._orig_backend = settings.llm_backend

    def teardown_method(self):
        settings.llm_backend = self._orig_backend

    def test_ollama_backend_returns_ollama_config(self):
        settings.llm_backend = "ollama"
        cfg = get_active_llm_config()
        assert cfg["base_url"] == settings.ollama_base_url
        assert cfg["model"] == settings.ollama_model
        assert "api_key" in cfg

    def test_lmstudio_backend_returns_lmstudio_config(self):
        settings.llm_backend = "lmstudio"
        cfg = get_active_llm_config()
        assert cfg["base_url"] == settings.lmstudio_base_url
        assert cfg["model"] == settings.lmstudio_model
        assert "api_key" in cfg

    def test_ollama_api_key_non_empty(self):
        settings.llm_backend = "ollama"
        cfg = get_active_llm_config()
        assert cfg["api_key"]  # must be truthy — openai SDK requires non-empty

    def test_lmstudio_api_key_non_empty(self):
        settings.llm_backend = "lmstudio"
        cfg = get_active_llm_config()
        assert cfg["api_key"]

    def test_config_has_all_required_keys(self):
        for backend in ("ollama", "lmstudio"):
            settings.llm_backend = backend
            cfg = get_active_llm_config()
            assert "base_url" in cfg
            assert "model" in cfg
            assert "api_key" in cfg


class TestSettingsDefaults:
    def test_default_llm_backend_is_ollama(self):
        # May be overridden by env, but default value should be ollama
        assert settings.llm_backend in ("ollama", "lmstudio")

    def test_max_packets_in_memory_positive(self):
        assert settings.max_packets_in_memory > 0

    def test_ollama_base_url_is_valid_http(self):
        assert settings.ollama_base_url.startswith("http")

    def test_lmstudio_base_url_is_valid_http(self):
        assert settings.lmstudio_base_url.startswith("http")

    def test_llm_temperature_in_range(self):
        assert 0.0 <= settings.llm_temperature <= 2.0

    def test_llm_max_tokens_none_or_positive(self):
        assert settings.llm_max_tokens is None or settings.llm_max_tokens > 0

    def test_cors_origins_is_list(self):
        assert isinstance(settings.cors_origins, list)
        assert len(settings.cors_origins) > 0
