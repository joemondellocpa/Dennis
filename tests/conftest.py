"""pytest configuration for Dennis tests."""
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set dummy env vars so config.py doesn't raise on import
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123:test")
os.environ.setdefault("TELEGRAM_ALLOWED_USERS", "12345")
