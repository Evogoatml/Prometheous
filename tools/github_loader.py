
"""
GitHub plugin loader: download a .py file from a raw GitHub URL.
Keeps the safety check (must be raw.githubusercontent.com and end in .py).
"""
import os
from typing import Any, Dict, Optional

import requests  # type: ignore  # optional dep

from swarm.base import BaseAgent


def download_plugin(url: str, dest_dir: Optional[str] = None) -> Dict[str, Any]:
    if not (url.startswith("https://raw.githubusercontent.com") and url.endswith(".py")):
        return {"status": "failed", "error": "URL must be a direct raw GitHub .py URL"}
    name = url.split("/")[-1]
    dest = os.path.join(dest_dir or os.path.dirname(__file__), name)
    try:
        resp = requests.get(url, timeout=30)
        if resp.status_code == 200:
            with open(dest, "w") as f:
                f.write(resp.text)
            return {"status": "ok", "name": name, "path": dest, "bytes": len(resp.text)}
        return {"status": "failed", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


class GitHubLoaderAgent(BaseAgent):
    name = "github_loader"
    role = "GitHub Loader"
    specialty = "download .py plugins from raw GitHub URLs"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        url = payload.get("url")
        if not url:
            return {"status": "failed", "agent": self.name, "error": "missing 'url' in payload"}
        result = download_plugin(url, dest_dir=payload.get("dest_dir"))
        result["agent"] = self.name
        return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(download_plugin(sys.argv[1]))
