# modules/google_integration.py
"""
Google API Integration module for Adaptive Vault.
"""

import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Path to your service-account JSON file
SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(__file__),
    "..",
    "keys",
    "google_service_account.json"
)
# Scope for the API you’ll use (modify accordingly)
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]

def get_service(api_name="drive", api_version="v3"):
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    service = build(api_name, api_version, credentials=creds)
    return service

def run_google_task():
    service = get_service()
    # Example: list first 10 files in Drive
    results = service.files().list(pageSize=10, fields="files(id, name)").execute()
    items = results.get('files', [])
    print("Files:")
    for item in items:
        print(f"{item['name']} ({item['id']})")
    # You can integrate this result into your audit log or decision-engine.
