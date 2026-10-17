"""Structured LLM calls (Gemini or Claude) with a response cache.

Adapted from kr-fund-ai-agent ``sentinel/agents/llm.py`` (via fund-reversing-ai). Used for
filing extraction (``riskprobe/extract.py``) and report wording (``riskprobe/report.py``);
numbers, dates and judgments never come from a model. Without a key every call returns
``(None, "llm unavailable")`` and the caller degrades.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from riskprobe import config

_GEMINI_CLIENTS: dict[str, object] = {}
_CACHE = None


def provider() -> str:
    """Active provider: 'gemini', 'anthropic' or 'none'."""
    if os.environ.get("RISKPROBE_DISABLE_LLM"):
        return "none"
    has_gemini = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    has_anthropic = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    choice = config.LLM_PROVIDER
    if choice == "gemini":
        return "gemini" if has_gemini else "none"
    if choice == "anthropic":
        return "anthropic" if has_anthropic else "none"
    if choice == "none":
        return "none"
    return "gemini" if has_gemini else "anthropic" if has_anthropic else "none"


def model() -> str:
    return config.GEMINI_MODEL if provider() == "gemini" else config.ANTHROPIC_MODEL


def _with_retry(fn, *args, attempts: int = 3, delay: float = 2.0):
    """Retry transient provider errors (free tiers return 429/503 under load)."""
    for i in range(attempts):
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001
            transient = type(exc).__name__ in {"ServerError", "RateLimitError", "APIConnectionError",
                                                "InternalServerError", "OverloadedError"} or "429" in str(exc)
            if not transient or i == attempts - 1:
                raise
            time.sleep(delay * (2**i))


def _structured_anthropic(schema, system: str, user: str):
    import anthropic

    resp = anthropic.Anthropic(max_retries=2, timeout=60.0).messages.parse(
        model=model(), max_tokens=8000, system=system,
        messages=[{"role": "user", "content": user}], output_format=schema,
    )
    return None if resp.stop_reason == "refusal" else resp.parsed_output


def _structured_gemini(schema, system: str, user: str):
    # Keep one client per key: a temporary client is closed when garbage-collected.
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or ""
    if key not in _GEMINI_CLIENTS:
        _GEMINI_CLIENTS[key] = genai.Client(api_key=key)
    resp = _GEMINI_CLIENTS[key].models.generate_content(
        model=model(), contents=user,
        config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                           response_schema=schema, max_output_tokens=8000, temperature=0.0),
    )
    if isinstance(resp.parsed, schema):
        return resp.parsed
    return schema.model_validate_json(resp.text) if resp.text else None


def _cache():
    global _CACHE
    if _CACHE is None and config.LLM_CACHE:
        try:
            import diskcache

            _CACHE = diskcache.Cache(str(config.LLM_CACHE_DIR), size_limit=200 * 2**20)
        except Exception:  # noqa: BLE001 - caching is an optimization only
            _CACHE = False
    # An empty diskcache.Cache is falsy (it defines __len__), so test identity, not truthiness.
    return None if _CACHE is None or _CACHE is False else _CACHE


def structured_call(schema, system: str, user: str):
    """Returns (parsed object or None, error string or None). Successful results are cached."""
    p = provider()
    if p == "none":
        return None, "llm unavailable"
    cache = _cache()
    raw = json.dumps([p, model(), schema.__name__, json.dumps(schema.model_json_schema(), sort_keys=True), system, user],
                     ensure_ascii=False)
    key = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if cache is not None and key in cache:
        try:
            return schema.model_validate_json(cache[key]), None
        except Exception:  # noqa: BLE001 - stale entry from an older schema
            del cache[key]
    fn = _structured_gemini if p == "gemini" else _structured_anthropic
    try:
        out = _with_retry(fn, schema, system, user)
    except Exception as exc:  # noqa: BLE001 - network/API failure must not break the caller
        return None, f"{p} error: {type(exc).__name__}"
    if out is None:
        return None, f"{p} returned no result"
    if cache is not None:
        cache[key] = out.model_dump_json()
    return out, None
