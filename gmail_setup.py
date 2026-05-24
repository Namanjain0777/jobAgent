"""
Run this ONCE on your local machine to get Gmail credentials.
After running, copy the output JSON into GitHub Secrets as GMAIL_CREDENTIALS.

Steps:
1. Go to https://console.cloud.google.com
2. Create a project → Enable Gmail API
3. OAuth consent screen → External → Add your email as test user
4. Credentials → Create OAuth client ID → Desktop app
5. Download the JSON → save as credentials.json in this folder
6. Run: python gmail_setup.py
7. Copy the printed JSON into GitHub Secret: GMAIL_CREDENTIALS
"""

import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def main():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                print("❌ credentials.json not found!")
                print("Download it from Google Cloud Console > Credentials > OAuth 2.0")
                return

            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    # Print the credentials JSON for GitHub Secrets
    creds_dict = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }

    print("\n✅ Success! Copy this into GitHub Secret 'GMAIL_CREDENTIALS':\n")
    print(json.dumps(creds_dict, indent=2))

if __name__ == "__main__":
    main()
