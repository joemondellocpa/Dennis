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


def _drive_service():
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=_get_credentials())


def _sheets_service():
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=_get_credentials())


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


# ── Google Drive ───────────────────────────────────────────────────────────

async def drive_list_files(query: str = "", max_results: int = 20) -> dict:
    """List files in Google Drive. Supports Drive search syntax."""
    def _fetch():
        service = _drive_service()
        q = query if query else "trashed = false"
        results = service.files().list(
            q=q,
            pageSize=max_results,
            fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
            orderBy="modifiedTime desc",
        ).execute()
        return {"success": True, "files": results.get("files", [])}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def drive_read_file(file_id: str) -> dict:
    """Download and return the text content of a Drive file (Docs exported as plain text, or raw for text files)."""
    def _fetch():
        service = _drive_service()
        meta = service.files().get(fileId=file_id, fields="mimeType, name").execute()
        mime = meta.get("mimeType", "")

        if mime == "application/vnd.google-apps.document":
            content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
        elif mime == "application/vnd.google-apps.spreadsheet":
            content = service.files().export(fileId=file_id, mimeType="text/csv").execute()
        else:
            content = service.files().get_media(fileId=file_id).execute()

        if isinstance(content, bytes):
            text = content.decode("utf-8", errors="replace")
        else:
            text = str(content)

        return {"success": True, "name": meta.get("name"), "content": text[:10000]}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def drive_upload_file(name: str, content: str, parent_folder_id: str = "", mime_type: str = "text/plain") -> dict:
    """Upload a text file to Google Drive."""
    def _upload():
        from googleapiclient.http import MediaInMemoryUpload
        service = _drive_service()
        metadata = {"name": name}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type)
        result = service.files().create(
            body=metadata, media_body=media,
            fields="id, name, webViewLink"
        ).execute()
        return {"success": True, "file_id": result["id"], "name": result["name"], "link": result.get("webViewLink")}

    try:
        return await asyncio.to_thread(_upload)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def drive_create_folder(name: str, parent_folder_id: str = "") -> dict:
    """Create a folder in Google Drive."""
    def _create():
        service = _drive_service()
        metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_folder_id:
            metadata["parents"] = [parent_folder_id]
        result = service.files().create(body=metadata, fields="id, name, webViewLink").execute()
        return {"success": True, "folder_id": result["id"], "name": result["name"], "link": result.get("webViewLink")}

    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Google Sheets ──────────────────────────────────────────────────────────

async def sheets_create(title: str, sheets: list[str] = None) -> dict:
    """Create a new Google Spreadsheet."""
    def _create():
        service = _sheets_service()
        body = {"properties": {"title": title}}
        if sheets:
            body["sheets"] = [{"properties": {"title": s}} for s in sheets]
        result = service.spreadsheets().create(body=body, fields="spreadsheetId,spreadsheetUrl").execute()
        return {"success": True, "spreadsheet_id": result["spreadsheetId"], "url": result["spreadsheetUrl"]}

    try:
        return await asyncio.to_thread(_create)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def sheets_read(spreadsheet_id: str, range_: str = "Sheet1") -> dict:
    """Read values from a Google Sheet range (e.g. 'Sheet1!A1:D10')."""
    def _fetch():
        service = _sheets_service()
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=range_
        ).execute()
        return {"success": True, "values": result.get("values", [])}

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def sheets_write(spreadsheet_id: str, range_: str, values: list[list]) -> dict:
    """Write values to a Google Sheet. values is a 2D list (rows × columns)."""
    def _write():
        service = _sheets_service()
        body = {"values": values}
        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=range_,
            valueInputOption="USER_ENTERED", body=body
        ).execute()
        return {"success": True, "updated_cells": result.get("updatedCells")}

    try:
        return await asyncio.to_thread(_write)
    except Exception as e:
        return {"success": False, "error": str(e)}


async def sheets_append(spreadsheet_id: str, range_: str, values: list[list]) -> dict:
    """Append rows to a Google Sheet."""
    def _append():
        service = _sheets_service()
        body = {"values": values}
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id, range=range_,
            valueInputOption="USER_ENTERED", insertDataOption="INSERT_ROWS", body=body
        ).execute()
        return {"success": True, "updated_cells": result.get("updates", {}).get("updatedCells")}

    try:
        return await asyncio.to_thread(_append)
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
