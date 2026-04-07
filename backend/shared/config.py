"""Shared configuration loaded from environment."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings, loaded from .env or environment variables."""

    # Mode
    apex_mode: str = "production"  # "development" or "production"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8020

    # LLM — Ollama
    ollama_base_url: str = "http://100.88.164.20:11434"
    ollama_conversation_model: str = "gemma4:e4b"
    ollama_architect_model: str = "deepseek-r1:14b"
    ollama_rag_model: str = "gemma4:e2b"
    ollama_codegen_model: str = "qwen3.5:9b"

    # LLM — VRAIN
    vrain_base_url: str = "https://ollama.gti-ia.upv.es"
    vrain_codegen_model: str = "qwen3:32b"

    # RAG
    chroma_host: str = "100.88.164.20"
    chroma_port: int = 8000

    # Database
    database_url: str = "sqlite:///./apex.db"

    # Logging
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
