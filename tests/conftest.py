"""Offline defaults: no LLM, no HTTP cache, no real keys."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _offline(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKPROBE_DISABLE_LLM", "1")
    for k in ("DART_API_KEY", "SEC_USER_AGENT", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("riskprobe.config.HTTP_CACHE", False)
    monkeypatch.setattr("riskprobe.config.CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr("riskprobe.config.LLM_CACHE", False)
