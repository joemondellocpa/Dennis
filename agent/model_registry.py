"""
Model registry – single source of truth for all LLM providers.

Returns a (client, model_id) tuple for any named provider. The client is
always AsyncOpenAI-compatible *except* for Claude, which returns an
AsyncAnthropic client. Callers that need to handle Claude differently can
check isinstance(client, AsyncAnthropic).

All providers except DeepSeek are DISABLED by default. Enable in .env and
validate with:
    python scripts/test_models.py

Provider summary:
    deepseek  – Default. Remote. Best general reasoning and tool-use.
    groq      – Remote. OpenAI-compatible. ~500 tok/s; best for low-latency.
    gemini    – Remote. OpenAI-compatible. 1M context; best for long documents.
    claude    – Remote. Anthropic SDK. Best writing quality (emails, posts).
    ollama    – Local. Ollama server. Cross-platform; works on Intel Macs.
"""
import config
from openai import AsyncOpenAI

# Lazy import – only required if CLAUDE_ENABLED=true
try:
    from anthropic import AsyncAnthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_client(provider: str) -> tuple:
    """
    Return (client, model_id) for the given provider name.

    Raises ValueError if the provider is unknown, disabled, or misconfigured.
    Call available_providers() first to check what's ready.
    """
    provider = provider.lower().strip()

    if provider == "deepseek":
        return (
            AsyncOpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL,
            ),
            config.DEEPSEEK_MODEL,
        )

    if provider == "groq":
        _require_enabled("Groq", config.GROQ_ENABLED, "GROQ_ENABLED")
        _require_key("GROQ_API_KEY", config.GROQ_API_KEY)
        return (
            AsyncOpenAI(
                api_key=config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            ),
            config.GROQ_MODEL,
        )

    if provider == "gemini":
        _require_enabled("Gemini", config.GEMINI_ENABLED, "GEMINI_ENABLED")
        _require_key("GEMINI_API_KEY", config.GEMINI_API_KEY)
        return (
            AsyncOpenAI(
                api_key=config.GEMINI_API_KEY,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            config.GEMINI_MODEL,
        )

    if provider == "claude":
        _require_enabled("Claude", config.CLAUDE_ENABLED, "CLAUDE_ENABLED")
        _require_key("ANTHROPIC_API_KEY", config.ANTHROPIC_API_KEY)
        if not _ANTHROPIC_AVAILABLE:
            raise ValueError(
                "anthropic package not installed. Run: pip install anthropic"
            )
        return (
            AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY),
            config.CLAUDE_MODEL,
        )

    if provider == "ollama":
        _require_enabled("Ollama", config.OLLAMA_ENABLED, "OLLAMA_ENABLED")
        # Ollama also exposes an OpenAI-compatible endpoint alongside /api/generate
        return (
            AsyncOpenAI(
                api_key="ollama",
                base_url=f"{config.LOCAL_MODEL_URL}/v1",
            ),
            config.LOCAL_MODEL,
        )

    raise ValueError(
        f"Unknown provider: {provider!r}. "
        f"Valid options: {', '.join(_ALL_PROVIDERS)}"
    )





def available_providers() -> list[str]:
    """
    Return list of provider names that are currently enabled and configured.
    DeepSeek is always included. Others require their *_ENABLED flag and key.
    """
    providers = ["deepseek"]

    if config.GROQ_ENABLED and config.GROQ_API_KEY:
        providers.append("groq")

    if config.GEMINI_ENABLED and config.GEMINI_API_KEY:
        providers.append("gemini")

    if (
        config.CLAUDE_ENABLED
        and config.ANTHROPIC_API_KEY
        and _ANTHROPIC_AVAILABLE
    ):
        providers.append("claude")

    if config.OLLAMA_ENABLED:
        providers.append("ollama")

    return providers


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ALL_PROVIDERS = ("deepseek", "groq", "gemini", "claude", "ollama")


def _require_enabled(name: str, flag: bool, env_var: str) -> None:
    if not flag:
        raise ValueError(
            f"{name} is not enabled. Set {env_var}=true in .env, "
            f"then run: python scripts/test_models.py"
        )


def _require_key(env_var: str, value: str) -> None:
    if not value:
        raise ValueError(f"{env_var} is not set in .env")
