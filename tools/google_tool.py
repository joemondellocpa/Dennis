"""
Google Workspace tool – Gmail, Calendar, Drive.
Uses OAuth2 with credentials.json from Google Cloud Console.

All Google API calls are blocking (synchronous). We run them in a thread
via asyncio.to_thread() so they don't block the event loop.
"""
import asyncio
import json
import base64
from datetime import datetime, timezone
from typing import Optional
import config


def _get_credentials():
    """Get or refresh Google OAuth2 credentials (blocking)."""
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    creds = None
    token_file = config.GOOGLE_TOKEN_FILE
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), config.GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.GOOGLE_CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    f"Google credentials file not found: {config.GOOGLE_CREDENTIALS_FILE}\n"
                    "Download from Google Cloud Console > APIs & Services > Credentials"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.GOOGLE_CREDENTIALS_FILE), config.GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(str(token_file), "w") as f:
            f.write(creds.to_json())
    return creds


def _gmail_service():
    from googleapiclient.discovery import build
    return build("gmail", "v1", credentials=_get_credentials())


def _calendar_service():
    from googleapiclient.discovery import build
    return build("calendar", "v3", credentials=_get_credentials())


# ── Email ──────────────────────────────────────────────────────────────────

async def list_emails(max_results: int = 10, query: str = "is:unread") -> dict:
    """List recent emails matching a Gmail query."""
    def _fetch():
        service = _gmail_service()
        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = results.get("messages", [])
        emails = []
        for msg in messages[:max_results]:
            m = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", ""),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
            })
        return {"success": True, "emails": emails}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_email_body(message_id: str) -> dict:
    """Get the full body of an email."""
    def _fetch():
        service = _gmail_service()
        m = service.users().messages().get(userId="me", id=message_id, format="full").execute()

        def extract_body(payload):
            if payload.get("mimeType") == "text/plain":
                data = payload.get("body", {}).get("data", "")
                return base64.urlsafe_b64decode(data + "==").decode(errors="replace")
            for part in payload.get("parts", []):
                result = extract_body(part)
                if result:
                    return result
            return ""

        body = extract_body(m["payload"])
        return {"success": True, "body": body[:5000]}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via Gmail."""
    def _send():
        from email.mime.text import MIMEText
        service = _gmail_service()
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        return {"success": True}

    try:
        return await asyncio.to_thread(_send)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Calendar ───────────────────────────────────────────────────────────────

async def list_calendar_events(max_results: int = 10, days_ahead: int = 7) -> dict:
    """List upcoming calendar events."""
    def _fetch():
        from datetime import timedelta
        service = _calendar_service()
        now = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now,
            timeMax=end,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = [
            {
                "summary": e.get("summary", ""),
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "end": e["end"].get("dateTime", e["end"].get("date")),
                "description": e.get("description", ""),
            }
            for e in events_result.get("items", [])
        ]
        return {"success": True, "events": events}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def create_calendar_event(
    summary: str, start_time: str, end_time: str,
    description: str = "", attendees: list[str] = None
) -> dict:
    """Create a calendar event. start_time/end_time in ISO 8601 format."""
    def _create():
        service = _calendar_service()
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_time, "timeZone": config.AGENT_TIMEZONE},
            "end": {"dateTime": end_time, "timeZone": config.AGENT_TIMEZONE},
        }
        if attendees:
            event["attendees"] = [{"email": a} for a in attendees]
        result = service.events().insert(calendarId="primary", body=event).execute()
        return {"success": True, "event_link": result.get("htmlLink")}

    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        return {"success": False, "error": str(e)}
