
"""
Google Drive API integration. Lazy-imports google libs so the module
loads even if google-api-python-client is not installed.

Agent: GoogleDriveAgent — registered with the orchestrator by name.
"""
import os
from typing import Any, Dict, Optional

from swarm.base import BaseAgent


SERVICE_ACCOUNT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "keys", "google_service_account.json"
)
SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]


def get_service(api_name: str = "drive", api_version: str = "v3"):
    """Build a Google API service client. Requires google-api-python-client."""
    try:
        from google.oauth2 import service_account  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-api-python-client not installed. "
            "pip install google-api-python-client google-auth"
        ) from e

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build(api_name, api_version, credentials=creds)


def list_drive_files(page_size: int = 10) -> list:
    service = get_service()
    results = service.files().list(pageSize=page_size, fields="files(id, name)").execute()
    return results.get("files", [])


def run_google_task() -> list:
    return list_drive_files()


class GoogleDriveAgent(BaseAgent):
    name = "google_drive"
    role = "Google Drive"
    specialty = "Google Drive API integration (read-only metadata)"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        action = payload.get("action", "list")
        try:
            if action == "list":
                files = list_drive_files(payload.get("page_size", 10))
                return {"status": "ok", "agent": self.name, "result": {"files": files}}
            return {"status": "ok", "agent": self.name, "result": {"note": f"unknown action: {action}"}}
        except Exception as e:
            return {"status": "failed", "agent": self.name, "error": str(e)}


if __name__ == "__main__":
    for f in run_google_task():
        print(f["name"], "(", f["id"], ")")
