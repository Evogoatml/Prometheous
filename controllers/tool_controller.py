"""
Tool controller — provides agent-facing tool execution.
Now wires in the structured tools/ modules (git_ops, github_loader, google_intergration, google_drive).
"""
import hashlib
import os
import platform
import subprocess
from typing import Any, Dict, Optional

# Integrate the moved-in tools/
try:
    from tools import git_ops
except Exception:
    git_ops = None

try:
    from tools import github_loader
except Exception:
    github_loader = None

try:
    from tools import google_intergration as google_int
except Exception:
    google_int = None

try:
    from tools import google_drive
except Exception:
    google_drive = None


class ToolController:
    """Agent-facing tool runner. Dispatch by tool name."""

    def run(self, tool: str, **kwargs) -> Dict[str, Any]:
        handler = getattr(self, f"_run_{tool}", None)
        if handler:
            return handler(**kwargs)
        return {"output": "", "error": f"Unknown tool: {tool}"}

    def _run_hash(self, text: str = "", algorithm: str = "sha256") -> Dict[str, Any]:
        h = hashlib.new(algorithm)
        h.update(text.encode())
        return {"output": h.hexdigest()}

    def _run_port_scan(self, host: str = "localhost", ports=None, engine: str = "auto",
                       timeout: float = 1.5, grab_banner: bool = True) -> Dict[str, Any]:
        # Delegate to the real async port scanner.
        from controllers.portscan import sync_scan, to_controller_output
        try:
            results = sync_scan(host, ports, engine=engine, timeout=timeout, grab_banner=grab_banner)
            if results and isinstance(results[0], dict) and "error" in results[0]:
                return {"output": "", "error": results[0]["error"]}
            return to_controller_output(results)
        except Exception as e:
            return {"output": "", "error": f"port_scan failed: {e}"}

    def _run_list_directory(self, path: str = ".") -> Dict[str, Any]:
        try:
            items = os.listdir(path)
            return {"output": "\n".join(items[:50])}
        except Exception as e:
            return {"output": "", "error": str(e)}

    def _run_system_info(self) -> Dict[str, Any]:
        info = {
            "system": platform.system(),
            "node": platform.node(),
            "release": platform.release(),
            "python": platform.python_version(),
        }
        return {"output": str(info)}

    # === Integrated from tools/git_ops.py ===
    def _run_git_clone(self, url: str = "", cwd: Optional[str] = None) -> Dict[str, Any]:
        if not git_ops:
            return {"error": "git_ops module not available"}
        return git_ops.clone_and_setup(url, cwd=cwd)

    # === Integrated from tools/github_loader.py ===
    def _run_github_download(self, url: str = "", dest_dir: Optional[str] = None) -> Dict[str, Any]:
        if not github_loader:
            return {"error": "github_loader module not available"}
        return github_loader.download_plugin(url, dest_dir=dest_dir)

    # === Integrated google tools (graceful if no keys/deps) ===
    def _run_google_task(self, **kwargs) -> Dict[str, Any]:
        if not google_int:
            return {"error": "google_intergration not available (or missing keys)"}
        try:
            return google_int.run_google_task()
        except Exception as e:
            return {"error": str(e), "note": "google may need service account key"}

    def _run_google_drive_list(self, **kwargs) -> Dict[str, Any]:
        if not google_drive:
            return {"error": "google_drive tool not wired"}
        try:
            # assume google_drive has similar entrypoints; call if present
            if hasattr(google_drive, "list_files"):
                return google_drive.list_files(**kwargs)
            return {"note": "google_drive module present but no list_files"}
        except Exception as e:
            return {"error": str(e)}


tools = ToolController()