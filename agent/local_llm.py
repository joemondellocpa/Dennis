"""
Local LLM client for cheap, high-frequency inference.

Supports two backends (tried in order of preference):
  1. Apple MLX  – fastest on Apple Silicon; uses Neural Engine natively
  2. Ollama     – cross-platform fallback; CPU/Metal

Routes classification and summarisation tasks away from the remote DeepSeek API,
saving tokens and API budget for complex multi-step reasoning.  Falls back
transparently to None so every caller can use the remote API when neither
local backend is available.

MLX setup (Mac mini / MacBook with M-series chip):
    pip install mlx-lm
    mlx_lm.server --model mlx-community/Llama-3.2-3B-Instruct-4bit --port 8080
    Set in .env: MLX_ENABLED=true
    Validate:    python scripts/test_models.py

Ollama setup:
    1. Install Ollama  https://ollama.ai/
    2. Pull a model:   ollama pull deepseek-r1:8b
    3. Set in .env:    OLLAMA_ENABLED=true

Recommended models by hardware:
    Mac mini 16 GB – deepseek-r1:8b  via Ollama, or Llama-3.1-8B via MLX
    Mac mini 8 GB  – llama3.2:3b     via Ollama, or Llama-3.2-3B via MLX
    Raspberry Pi 5 – llama3.2:1b     via Ollama only (no MLX on non-Apple)
"""
import asyncio
from typing import Optional

import httpx
from loguru import logger

import config

# Suppress repeated "not reachable" log spam after several consecutive failures.
_consecutive_failures: int = 0
_MAX_FAILURES_BEFORE_SILENCE = 3


async def _classify_mlx(prompt: str, system: str = "", max_tokens: int = 200) -> Optional[str]:
    """
    Call the MLX local server (OpenAI-compatible /v1/chat/completions).
    Returns None on any error so the caller can fall back to Ollama or remote.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(timeout=config.LOCAL_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{config.MLX_MODEL_URL}/v1/chat/completions",
                json={
                    "model": config.MLX_MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.0,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text or None

    except httpx.ConnectError:
        logger.debug(
            f"MLX server not reachable at {config.MLX_MODEL_URL} – "
            "trying Ollama or remote API"
        )
        return None
    except httpx.TimeoutException:
        logger.warning(f"MLX server timed out after {config.LOCAL_LLM_TIMEOUT}s")
        return None
    except Exception as e:
        logger.warning(f"MLX error: {e}")
        return None


async def _classify_ollama(prompt: str, system: str = "", max_tokens: int = 200) -> Optional[str]:
    """
    Call Ollama via its /api/generate endpoint.
    Returns None on any error so the caller can fall back to the remote API.
    """
    global _consecutive_failures

    try:
        payload: dict = {
            "model": config.LOCAL_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": 0.0,
            },
        }
        if system:
            payload["system"] = system

        async with httpx.AsyncClient(timeout=config.LOCAL_LLM_TIMEOUT) as client:
            resp = await client.post(
                f"{config.LOCAL_MODEL_URL}/api/generate",
                json=payload,
            )
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            _consecutive_failures = 0  # Reset on success
            return text or None

    except httpx.ConnectError:
        _consecutive_failures += 1
        if _consecutive_failures <= _MAX_FAILURES_BEFORE_SILENCE:
            logger.debug(
                f"Ollama not reachable at {config.LOCAL_MODEL_URL} – "
                "falling back to remote API "
                "(set OLLAMA_ENABLED=false in .env to silence this)"
            )
        return None

    except httpx.TimeoutException:
        _consecutive_failures += 1
        logger.warning(
            f"Ollama timed out after {config.LOCAL_LLM_TIMEOUT}s – "
            "falling back to remote API"
        )
        return None

    except Exception as e:
        _consecutive_failures += 1
        logger.warning(f"Ollama error: {e} – falling back to remote API")
        return None


async def classify(
    prompt: str,
    system: str = "",
    max_tokens: int = 200,
) -> Optional[str]:
    """
    Send a prompt to the best available local model and return the response text.

    Priority: MLX (if enabled) → Ollama (if enabled) → None (caller uses remote API).
    Uses temperature=0 for deterministic classification.
    """
    if config.MLX_ENABLED:
        result = await _classify_mlx(prompt, system, max_tokens)
        if result is not None:
            return result
        # MLX unreachable – fall through to Ollama

    if config.OLLAMA_ENABLED:
        return await _classify_ollama(prompt, system, max_tokens)

    return None


async def is_available() -> bool:
    """
    Check whether any local backend is running and ready.

    Tries MLX first, then Ollama. Useful for startup diagnostics; not required
    before each classify() call since that already falls back gracefully.
    """
    if config.MLX_ENABLED:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{config.MLX_MODEL_URL}/v1/models")
                if resp.status_code == 200:
                    return True
        except Exception:
            pass  # Fall through to Ollama check

    if config.OLLAMA_ENABLED:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{config.LOCAL_MODEL_URL}/api/tags")
                resp.raise_for_status()
                models = [m.get("name", "") for m in resp.json().get("models", [])]
                prefix = config.LOCAL_MODEL.split(":")[0]
                return any(m.startswith(prefix) for m in models)
        except Exception:
            return False

    return False
