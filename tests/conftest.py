"""pytest configuration for Dennis tests."""
import sys
import os
from unittest.mock import MagicMock

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set dummy env vars so config.py doesn't raise on import
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_ALLOWED_USERS", "12345")


def _mock_embedding_function():
    """Return a ChromaDB-compatible embedding function that avoids network downloads in tests."""
    from chromadb import EmbeddingFunction, Documents, Embeddings

    class _StubEF(EmbeddingFunction):
        def __init__(self):
            pass

        def __call__(self, input: Documents) -> Embeddings:
            return [[0.0] * 384 for _ in input]

        def name(self) -> str:
            return "stub"

    return _StubEF()


# Patch before any test imports agent.memory so the model is never downloaded
import agent.memory
agent.memory._make_embedding_function = _mock_embedding_function
