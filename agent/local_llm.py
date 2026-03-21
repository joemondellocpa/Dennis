"""
Local LLM client via Ollama for cheap, high-frequency inference.

Routes classification and summarisation tasks away from the remote DeepSeek API,
saving tokens and API budget for complex multi-step reasoning.  Falls back
transparently to None so every caller can use the remote API when Ollama is
unavailable.

Setup:
    1. Install Ollama  https://ollama.ai/
    2. Pull a model:   ollama pull deepseek-r1:8b
    3. Set in .env:    OLLAMA_ENABLED=true

Recommended models by hardware:
    Mac mini 16 GB – deepseek-r1:8b  (Q4, ~15 tok/s)
    Mac mini 8 GB  – llama3.2:3b     (Q4, ~25 tok/s)
    Raspberry Pi 5 – llama3.2:1b     (Q4, ~4 tok/s)
"""
import asyncio
from typing import Optional

import httpx
from loguru import logger

import config

# Suppress repeated "not reachable" log spam after several consecutive failures.
_consecutive_failures: int = 0
_MAX_FAILURES_BEFORE_SILENCE = 3


async def classify(
    prompt: str,
    system: str = "",
    max_tokens: int = 200,
) -> Optional[str]:
    """
    Send a prompt to the local Ollama model and return the response text.

    Returns None if Ollama is unavailable – callers should fall back to the
    remote DeepSeek API.  Uses temperature=0 for deterministic classification.
    """
    global _consecutive_failures

    if not config.OLLAMA_ENABLED:
        return None

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
        logger.warning(f"Local LLM error: {e} – falling back to remote API")
        return None


async def is_available() -> bool:
    """
    Check whether Ollama is running and the configured model is available.

    Useful for startup diagnostics; not required before each call (classify()
    already falls back gracefully).
    """
    if not config.OLLAMA_ENABLED:
        return False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{config.LOCAL_MODEL_URL}/api/tags")
            resp.raise_for_status()
            models = [m.get("name", "") for m in resp.json().get("models", [])]
            # Match by model family prefix (e.g. "deepseek-r1" matches "deepseek-r1:8b")
            prefix = config.LOCAL_MODEL.split(":")[0]
            return any(m.startswith(prefix) for m in models)
    except Exception:
        return False
