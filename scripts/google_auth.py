"""
One-time Google OAuth2 authorization flow.
Run this ONCE on the Mac mini (with a browser) to generate the token file.
After that, Dennis will refresh tokens automatically.

Usage: python scripts/google_auth.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

import config
from google_auth_oauthlib.flow import InstalledAppFlow

if not config.GOOGLE_CREDENTIALS_FILE.exists():
    print(f"❌ Google credentials file not found: {config.GOOGLE_CREDENTIALS_FILE}")
    print("\nTo fix this:")
    print("1. Go to https://console.cloud.google.com/")
    print("2. Create/select a project")
    print("3. Enable Gmail API, Google Calendar API, Google Drive API")
    print("4. Create OAuth 2.0 credentials (Desktop app)")
    print("5. Download as 'credentials.json' and place it in the Dennis folder")
    sys.exit(1)

print("Opening browser for Google authorization...")
print("Please log in and grant permissions.\n")

flow = InstalledAppFlow.from_client_secrets_file(
    str(config.GOOGLE_CREDENTIALS_FILE),
    config.GOOGLE_SCOPES,
)
creds = flow.run_local_server(port=0)

config.GOOGLE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(str(config.GOOGLE_TOKEN_FILE), "w") as f:
    f.write(creds.to_json())

print(f"\n✅ Google authorization complete! Token saved to: {config.GOOGLE_TOKEN_FILE}")
print("Dennis can now access your Gmail, Calendar, and Drive.")
