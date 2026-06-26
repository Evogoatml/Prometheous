
"""
Git operations: clone a repo, run its setup. Lazy-imports nothing heavy.
"""
import os
import subprocess
from typing import Any, Dict, Optional

from swarm.base import BaseAgent


def clone_repo(url: str, cwd: Optional[str] = None) -> str:
    repo_name = url.split("/")[-1].replace(".git", "")
    target_dir = os.path.join(cwd or os.getcwd(), repo_name)
    if not os.path.exists(target_dir):
        subprocess.run(["git", "clone", url], check=True, cwd=cwd)
    return target_dir


def setup_repo(path: str) -> bool:
    log_path = os.path.join(path, "build_report.log")
    success = True
    with open(log_path, "w") as log:
        if os.path.exists(os.path.join(path, "requirements.txt")):
            r = subprocess.run(
                ["pip", "install", "-r", "requirements.txt"],
                cwd=path, capture_output=True, text=True,
            )
            log.write(r.stdout + r.stderr)
            success = r.returncode == 0
        elif os.path.exists(os.path.join(path, "setup.py")):
            r = subprocess.run(
                ["python3", "setup.py", "install"],
                cwd=path, capture_output=True, text=True,
            )
            log.write(r.stdout + r.stderr)
            success = r.returncode == 0
        else:
            log.write("No setup.py or requirements.txt found.\n")
            success = False
    return success


def clone_and_setup(url: str, cwd: Optional[str] = None) -> Dict[str, Any]:
    try:
        target = clone_repo(url, cwd=cwd)
        ok = setup_repo(target)
        return {"status": "ok" if ok else "partial", "path": target, "log": os.path.join(target, "build_report.log")}
    except subprocess.CalledProcessError as e:
        return {"status": "failed", "error": str(e)}


class GitOpsAgent(BaseAgent):
    name = "git_ops"
    role = "Git Ops"
    specialty = "clone and set up Git repositories"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        url = payload.get("url")
        if not url:
            return {"status": "failed", "agent": self.name, "error": "missing 'url' in payload"}
        return clone_and_setup(url, cwd=payload.get("cwd"))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(clone_and_setup(sys.argv[1]))
