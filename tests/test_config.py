"""Tests for src/config.py — provider resolution and validation."""

import importlib
import sys

import pytest


def _reload_config(monkeypatch, **env_vars):
    """Reload src.config with a controlled environment so module-level
    validation (MODEL_PROVIDER check) re-runs against the new env vars."""
    for key in ["MODEL_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL_ID", "OLLAMA_MODEL_ID", "OLLAMA_HOST"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("src.config", None)
    import src.config as config

    return config


def test_default_provider_is_ollama(monkeypatch):
    config = _reload_config(monkeypatch)
    assert config.MODEL_PROVIDER == "ollama"


def test_ollama_config_has_no_api_key_requirement(monkeypatch):
    config = _reload_config(monkeypatch, MODEL_PROVIDER="ollama")
    cfg = config.get_model_config()
    assert cfg["model_provider"] == "ollama"
    assert "model_id" in cfg["model_settings"]


def test_gemini_without_api_key_raises(monkeypatch):
    config = _reload_config(monkeypatch, MODEL_PROVIDER="gemini")
    with pytest.raises(EnvironmentError):
        config.get_model_config()


def test_gemini_routes_through_litellm(monkeypatch):
    config = _reload_config(monkeypatch, MODEL_PROVIDER="gemini", GEMINI_API_KEY="fake-key")
    cfg = config.get_model_config()
    # Verified empirically: strands_tools.create_model has no native "gemini"
    # provider, so Gemini must be routed via litellm's "gemini/<model>" prefix.
    assert cfg["model_provider"] == "litellm"
    assert cfg["model_settings"]["model_id"].startswith("gemini/")


def test_unsupported_provider_raises(monkeypatch):
    monkeypatch.setenv("MODEL_PROVIDER", "bedrock")
    sys.modules.pop("src.config", None)
    with pytest.raises(ValueError):
        importlib.import_module("src.config")
