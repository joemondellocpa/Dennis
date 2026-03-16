"""
Webhook server for event-driven triggers.

Runs as a FastAPI app in a background thread alongside the Telegram bot.
Accepts POST requests from external services (GitHub, email forwarders, etc.)
and queues events for the agent to process on the next autonomous tick.

Endpoints:
  POST /webhook/github   – GitHub repository events
  POST /webhook/generic  – Generic JSON events from any source

Authentication: WEBHOOK_SECRET header (set WEBHOOK_SECRET in .env).
If WEBHOOK_SECRET is empty, the server starts in insecure mode (warns on startup).

To expose to the internet: use ngrok or Cloudflare Tunnel:
  ngrok http 8765
  Then configure https://<your-ngrok-url>/webhook/github as your GitHub webhook URL.
"""
import asyncio
import hashlib
import hmac
import json
import threading
from typing import Optional

from loguru import logger

import config


def create_app(memory, notifier=None):
    """Create and return a FastAPI application instance."""
    try:
        from fastapi import FastAPI, Request, HTTPException, Header
    except ImportError:
        logger.warning("fastapi not installed – webhook server disabled")
        return None

    app = FastAPI(title="Dennis Webhook Server", docs_url=None, redoc_url=None)

    def _verify_secret(body: bytes, signature: Optional[str]) -> bool:
        if not config.WEBHOOK_SECRET:
            return True  # Insecure mode
        if not signature:
            return False
        expected = "sha256=" + hmac.new(
            config.WEBHOOK_SECRET.encode(), body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    @app.post("/webhook/github")
    async def github_webhook(
        request: Request,
        x_hub_signature_256: Optional[str] = Header(None),
        x_github_event: Optional[str] = Header(None),
    ):
        body = await request.body()
        if not _verify_secret(body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        event_type = x_github_event or "unknown"
        event_id = memory.save_webhook_event("github", event_type, payload)
        logger.info(f"GitHub webhook received: {event_type} → event_id={event_id}")

        return {"status": "queued", "event_id": event_id}

    @app.post("/webhook/generic")
    async def generic_webhook(request: Request, x_webhook_secret: Optional[str] = Header(None)):
        body = await request.body()
        if config.WEBHOOK_SECRET and x_webhook_secret != config.WEBHOOK_SECRET:
            raise HTTPException(status_code=401, detail="Invalid secret")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        source = payload.get("source", "generic")
        event_type = payload.get("event_type", "event")
        event_id = memory.save_webhook_event(source, event_type, payload)
        logger.info(f"Generic webhook received: {source}/{event_type} → event_id={event_id}")

        return {"status": "queued", "event_id": event_id}

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": config.AGENT_NAME}

    return app


def start_webhook_server(memory, notifier=None):
    """Start the webhook server in a daemon thread. Returns the thread."""
    if config.WEBHOOK_PORT == 0:
        logger.info("Webhook server disabled (WEBHOOK_PORT=0)")
        return None

    if not config.WEBHOOK_SECRET:
        logger.warning(
            "⚠️  WEBHOOK_SECRET is not set – webhook server running in insecure mode. "
            "Set WEBHOOK_SECRET in .env to require authentication."
        )

    app = create_app(memory, notifier)
    if app is None:
        return None

    def _run():
        try:
            import uvicorn
            uvicorn.run(
                app,
                host="0.0.0.0",
                port=config.WEBHOOK_PORT,
                log_level="warning",
            )
        except Exception as e:
            logger.error(f"Webhook server failed: {e}")

    thread = threading.Thread(target=_run, name="webhook-server", daemon=True)
    thread.start()
    logger.info(f"Webhook server started on port {config.WEBHOOK_PORT}")
    return thread
