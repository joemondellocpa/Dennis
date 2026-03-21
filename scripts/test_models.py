"""
Model validation script – run this before enabling any new model in production.

Tests every configured provider with a lightweight ping prompt, measures
response time, and reports PASS/FAIL clearly. Only tests providers that are
currently enabled in .env.

Usage:
    python scripts/test_models.py              # test all enabled providers
    python scripts/test_models.py groq gemini  # test specific providers only

A provider must PASS here before it is safe to use in Dennis.
"""
import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import config

# ── ANSI colours ────────────────────────────────────────────────────────────
GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
BOLD  = "\033[1m"
RESET = "\033[0m"

PING_PROMPT = "Reply with exactly two words: 'model ok'. Nothing else."
MAX_TOKENS  = 20


# ── Per-provider test functions ──────────────────────────────────────────────

async def _test_openai_compatible(provider: str) -> tuple[bool, str, float]:
    """Test any OpenAI-compatible provider. Returns (passed, detail, elapsed_s)."""
    from agent.model_registry import get_client
    try:
        client, model_id = get_client(provider)
        start = time.perf_counter()
        response = await client.chat.completions.create(
            model=model_id,
            messages=[{"role": "user", "content": PING_PROMPT}],
            max_tokens=MAX_TOKENS,
            temperature=0.0,
        )
        elapsed = time.perf_counter() - start
        text = response.choices[0].message.content.strip()
        return True, f'"{text}"', elapsed
    except Exception as e:
        return False, str(e), 0.0


async def _test_claude() -> tuple[bool, str, float]:
    """Test Claude via the Anthropic SDK."""
    try:
        from anthropic import AsyncAnthropic
    except ImportError:
        return False, "anthropic package not installed – run: pip install anthropic", 0.0

    try:
        client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        start = time.perf_counter()
        response = await client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": PING_PROMPT}],
        )
        elapsed = time.perf_counter() - start
        text = response.content[0].text.strip()
        return True, f'"{text}"', elapsed
    except Exception as e:
        return False, str(e), 0.0


async def _test_mlx() -> tuple[bool, str, float]:
    """Test the local MLX server."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            start = time.perf_counter()
            resp = await http.post(
                f"{config.MLX_MODEL_URL}/v1/chat/completions",
                json={
                    "model": config.MLX_MODEL,
                    "messages": [{"role": "user", "content": PING_PROMPT}],
                    "max_tokens": MAX_TOKENS,
                    "temperature": 0.0,
                },
            )
            elapsed = time.perf_counter() - start
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return True, f'"{text}"', elapsed
    except Exception as e:
        return False, str(e), 0.0


async def _test_ollama() -> tuple[bool, str, float]:
    """Test the local Ollama server."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            start = time.perf_counter()
            resp = await http.post(
                f"{config.LOCAL_MODEL_URL}/api/generate",
                json={
                    "model": config.LOCAL_MODEL,
                    "prompt": PING_PROMPT,
                    "stream": False,
                    "options": {"num_predict": MAX_TOKENS, "temperature": 0.0},
                },
            )
            elapsed = time.perf_counter() - start
            resp.raise_for_status()
            text = resp.json().get("response", "").strip()
            return True, f'"{text}"', elapsed
    except Exception as e:
        return False, str(e), 0.0


# ── Test dispatch table ──────────────────────────────────────────────────────

async def _run_test(provider: str) -> tuple[bool, str, float]:
    if provider == "claude":
        return await _test_claude()
    if provider == "mlx":
        return await _test_mlx()
    if provider == "ollama":
        return await _test_ollama()
    # deepseek, groq, gemini – all OpenAI-compatible
    return await _test_openai_compatible(provider)


def _provider_config_summary(provider: str) -> str:
    summaries = {
        "deepseek": f"model={config.DEEPSEEK_MODEL}",
        "groq":     f"model={config.GROQ_MODEL}",
        "gemini":   f"model={config.GEMINI_MODEL}",
        "claude":   f"model={config.CLAUDE_MODEL}",
        "mlx":      f"server={config.MLX_MODEL_URL}  model={config.MLX_MODEL}",
        "ollama":   f"server={config.LOCAL_MODEL_URL}  model={config.LOCAL_MODEL}",
    }
    return summaries.get(provider, "")


# ── Main ─────────────────────────────────────────────────────────────────────

async def main(targets: list[str]) -> None:
    from agent.model_registry import available_providers

    enabled = available_providers()

    if targets:
        # Filter to only requested providers that are also enabled
        unknown = [p for p in targets if p not in
                   ("deepseek", "groq", "gemini", "claude", "mlx", "ollama")]
        if unknown:
            print(f"{RED}Unknown provider(s): {', '.join(unknown)}{RESET}")
            sys.exit(1)
        not_enabled = [p for p in targets if p not in enabled]
        if not_enabled:
            print(
                f"{YELLOW}Warning: {', '.join(not_enabled)} not enabled in .env "
                f"– skipping{RESET}"
            )
        to_test = [p for p in targets if p in enabled]
    else:
        to_test = enabled

    if not to_test:
        print(f"{YELLOW}No providers enabled. Set *_ENABLED=true in .env first.{RESET}")
        sys.exit(0)

    print(f"\n{BOLD}Dennis model validation{RESET}")
    print(f"Testing {len(to_test)} provider(s): {', '.join(to_test)}\n")
    print(f"{'Provider':<12} {'Config':<45} {'Result':<8} {'Time':>7}  Response")
    print("─" * 100)

    results = await asyncio.gather(*[_run_test(p) for p in to_test])

    all_passed = True
    for provider, (passed, detail, elapsed) in zip(to_test, results):
        cfg = _provider_config_summary(provider)
        if passed:
            status = f"{GREEN}PASS{RESET}"
            time_str = f"{elapsed:.2f}s"
        else:
            status = f"{RED}FAIL{RESET}"
            time_str = "—"
            all_passed = False
        print(f"{provider:<12} {cfg:<45} {status:<8} {time_str:>7}  {detail}")

    print()
    if all_passed:
        print(f"{GREEN}{BOLD}All providers passed.{RESET} Safe to use in Dennis.")
    else:
        print(
            f"{RED}{BOLD}One or more providers failed.{RESET} "
            "Do not enable failed providers in production."
        )
        sys.exit(1)


if __name__ == "__main__":
    targets = [a.lower() for a in sys.argv[1:]]
    asyncio.run(main(targets))
