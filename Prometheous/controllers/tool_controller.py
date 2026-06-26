"""
Tool controller — provides agent-facing tool execution.
Wraps subprocess calls and system utilities.
"""
import hashlib
import os
import platform
import shutil
import subprocess
from typing import Any, Dict, Optional


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

    def _run_port_scan(self, host: str = "localhost", ports=None) -> Dict[str, Any]:
        if ports is None:
            ports = [80, 443, 22]
        results = []
        for port in ports:
            result = subprocess.run(
                ["timeout", "2", "bash", "-c", f"echo >/dev/tcp/{host}/{port} 2>/dev/null"],
                capture_output=True, text=True, timeout=3
            )
            status = "open" if result.returncode == 0 else "closed"
            results.append({"port": port, "status": status})
        return {"output": str(results)}

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


tools = ToolController()