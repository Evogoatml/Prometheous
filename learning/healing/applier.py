"""
Hybrid applier — worktree-first patch application with gated live mode.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from learning.healing.proposal_log import HEALING_DIR
from learning.healing.patcher import PatchProposal
from learning.healing.validator import PatchValidator

try:
    from utils.config import cfg
    ROOT = cfg.ROOT
except Exception:
    ROOT = Path(__file__).resolve().parents[2]

WORKTREE_DIR = HEALING_DIR / "worktrees"
BACKUP_DIR = HEALING_DIR / "backups"
LIVE_ENV = "PROM_HEALING_LIVE_APPLY"


class HybridApplier:
    def __init__(self) -> None:
        self._validator = PatchValidator()
        WORKTREE_DIR.mkdir(parents=True, exist_ok=True)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def apply_from_log_entry(
        self,
        entry: Dict[str, Any],
        *,
        proposal_index: int = 0,
        live: bool = False,
    ) -> Dict[str, Any]:
        proposal_id = entry.get("id", "unknown")
        proposals = entry.get("proposals") or []
        if not proposals:
            return {"status": "error", "error": "no valid proposals in entry"}

        if proposal_index >= len(proposals):
            proposal_index = 0
        proposal = proposals[proposal_index]

        target = proposal.get("file") or (entry.get("fault") or {}).get("primary_file")
        if not target:
            return {"status": "error", "error": "no target file in proposal"}

        source_path = Path(target)
        if not source_path.is_absolute():
            source_path = (ROOT / source_path).resolve()
        if not source_path.is_file():
            return {"status": "error", "error": f"source missing: {source_path}"}

        try:
            rel = source_path.relative_to(ROOT)
        except ValueError:
            return {"status": "error", "error": "target outside project root"}

        original = proposal.get("original", "")
        patched = proposal.get("patched", "")
        if not original or not patched:
            return {"status": "error", "error": "proposal missing original/patched body"}

        content = source_path.read_text(encoding="utf-8", errors="replace")
        new_content, replaced = self._replace_in_source(content, original, patched, proposal.get("line"))
        if not replaced:
            return {"status": "error", "error": "original snippet not found in source file"}

        block = PatchProposal(
            strategy=proposal.get("strategy", ""),
            description=proposal.get("description", ""),
            file=str(source_path),
            line=proposal.get("line"),
            original=original,
            patched=patched,
            diff=proposal.get("diff", ""),
            confidence=float(proposal.get("confidence", 0)),
        )
        ok, msg = self._validator.validate_proposal(block)
        if not ok:
            return {"status": "error", "error": f"patch block invalid: {msg}"}

        if live:
            if os.getenv(LIVE_ENV, "").lower() not in ("1", "true", "yes"):
                return {
                    "status": "error",
                    "error": f"live apply blocked — set {LIVE_ENV}=1 to enable",
                }
            return self._apply_live(source_path, rel, new_content, proposal_id, proposal)

        return self._apply_worktree(rel, new_content, proposal_id, proposal, source_path)

    def _replace_in_source(
        self,
        content: str,
        original: str,
        patched: str,
        line_hint: Optional[int],
    ) -> Tuple[str, bool]:
        if original in content:
            return content.replace(original, patched, 1), True

        lines = content.splitlines(keepends=True)
        if line_hint and 1 <= line_hint <= len(lines):
            idx = line_hint - 1
            if lines[idx].strip() == original.strip():
                indent = lines[idx][: len(lines[idx]) - len(lines[idx].lstrip())]
                patched_lines = patched.splitlines(keepends=True)
                if patched_lines and not patched.startswith(indent) and patched_lines[0].strip():
                    patched_lines = [indent + pl if not pl.startswith(indent) else pl for pl in patched_lines]
                lines[idx : idx + 1] = patched_lines
                return "".join(lines), True

        for i, line in enumerate(lines):
            if line.strip() == original.strip():
                indent = line[: len(line) - len(line.lstrip())]
                patched_lines = patched.splitlines(keepends=True)
                if patched_lines and patched_lines[0].strip():
                    patched_lines = [
                        (indent + pl.lstrip()) if not pl.startswith(indent) else pl
                        for pl in patched_lines
                    ]
                lines[i : i + 1] = patched_lines
                return "".join(lines), True

        return content, False

    def _apply_worktree(
        self,
        rel: Path,
        new_content: str,
        proposal_id: str,
        proposal: Dict[str, Any],
        source_path: Path,
    ) -> Dict[str, Any]:
        out_dir = WORKTREE_DIR / proposal_id
        out_path = out_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, out_path)
        out_path.write_text(new_content, encoding="utf-8")

        compiled, compile_msg = self._compile_check(out_path)
        return {
            "status": "ok",
            "mode": "worktree",
            "proposal_id": proposal_id,
            "strategy": proposal.get("strategy"),
            "source": str(source_path),
            "worktree_path": str(out_path),
            "relative_path": str(rel),
            "compile_ok": compiled,
            "compile_msg": compile_msg,
            "live_path": str(source_path),
            "note": "Review worktree file; live apply requires explicit gate",
        }

    def _apply_live(
        self,
        source_path: Path,
        rel: Path,
        new_content: str,
        proposal_id: str,
        proposal: Dict[str, Any],
    ) -> Dict[str, Any]:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup_path = BACKUP_DIR / f"{stamp}-{rel.name}"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, backup_path)

        worktree_result = self._apply_worktree(rel, new_content, proposal_id, proposal, source_path)
        if worktree_result.get("status") != "ok":
            return worktree_result

        source_path.write_text(new_content, encoding="utf-8")
        compiled, compile_msg = self._compile_check(source_path)
        return {
            "status": "ok" if compiled else "warning",
            "mode": "live",
            "proposal_id": proposal_id,
            "strategy": proposal.get("strategy"),
            "backup_path": str(backup_path),
            "applied_path": str(source_path),
            "worktree_path": worktree_result.get("worktree_path"),
            "compile_ok": compiled,
            "compile_msg": compile_msg,
        }

    def _compile_check(self, path: Path) -> Tuple[bool, str]:
        if path.suffix != ".py":
            return True, "non-python — skipped compile"
        try:
            import py_compile
            py_compile.compile(str(path), doraise=True)
            return True, "compile ok"
        except Exception as exc:
            return False, str(exc)