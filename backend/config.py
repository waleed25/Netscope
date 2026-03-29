from pydantic_settings import BaseSettings
from typing import Literal, Optional


class Settings(BaseSettings):
    # LLM backend: "ollama" or "lmstudio"
    llm_backend: Literal["ollama", "lmstudio"] = "ollama"

    # Ollama settings
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3.5:9b"

    # LM Studio settings
    lmstudio_base_url: str = "http://localhost:1234/v1"
    lmstudio_model: str = "mistral-7b-instruct-v0.3-q4_k_m"

    # Shared LLM settings
    llm_temperature: float = 0.3
    llm_max_tokens: Optional[int] = None  # None = unlimited (model decides)
    llm_max_tool_rounds: int = 4  # max tool calls per chat turn
    exec_timeout: int = 30  # max seconds for exec tool commands
    autonomous_max_rounds: int = 20  # max tool calls in autonomous mode

    # Capture settings
    auto_insight_interval: int = 50  # trigger insight every N packets
    max_packets_in_memory: int = 5000
    capture_timeout: int = 0  # 0 = no timeout

    # Agent memory settings
    memory_enabled:          bool = True     # persistent memory across sessions
    persona_file:            str | None = None  # optional custom persona markdown file

    # Agent skills settings
    tools_token_budget:      int  = 400      # max tokens for tool section in system prompt
    skill_hot_reload:        bool = True     # reserved for future file-watcher support

    # RAG settings
    rag_data_dir:            str  = "data"   # where chroma_db/ and bm25_corpus.pkl live
    rag_enrichment_enabled:  bool = False    # disabled: saves 200+ LLM calls per ingest
    rag_window_size:         int  = 3        # context sentences each side of embed unit
    rag_min_similarity:      float = 0.30   # below this → "not in KB" response
    rag_faithfulness_check:  bool = False    # disabled: HHEM model is 400 MB, slow on CPU

    # API settings
    host: str = "127.0.0.1"
    port: int = 8000
    # When running inside Electron the renderer is a file:// page; allow that
    # alongside the standard dev-server origins.
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "file://",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()


def get_active_llm_config() -> dict:
    """Return the active LLM base_url and model based on current backend setting."""
    if settings.llm_backend == "ollama":
        return {
            "base_url": settings.ollama_base_url,
            "model": settings.ollama_model,
            "api_key": "ollama",  # Ollama requires a non-empty api_key
        }
    else:
        return {
            "base_url": settings.lmstudio_base_url,
            "model": settings.lmstudio_model,
            "api_key": "lmstudio",
        }
