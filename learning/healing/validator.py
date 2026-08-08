"""
Validate proposed patches without applying them.
"""
from __future__ import annotations

import ast
import compileall
import tempfile
from pathlib import Path
from typing import Tuple

from learning.healing.patcher import PatchProposal


class PatchValidator:
    """Syntax-check proposed patch bodies."""

    def validate_proposal(self, proposal: PatchProposal) -> Tuple[bool, str]:
        patched = proposal.patched.strip()
        if not patched:
            return False, "empty patch"

        if proposal.strategy == "import_fix" and "<symbol>" in patched:
            return True, "import path hint (manual symbol required)"

        if proposal.strategy in {"attribute_guard", "dict_get", "none_guard", "path_guard", "index_guard"}:
            return self._validate_snippet(patched)

        if proposal.strategy == "generic_try_except":
            return self._validate_snippet(patched)

        return self._validate_snippet(patched)

    def _validate_snippet(self, source: str) -> Tuple[bool, str]:
        try:
            ast.parse(source)
            return True, "syntax ok"
        except SyntaxError as exc:
            return False, f"syntax error: {exc.msg} (line {exc.lineno})"

    def validate_file_replace(self, filepath: str, new_content: str) -> Tuple[bool, str]:
        """Full-file validation — used only if a future apply path is added."""
        ok, msg = self._validate_snippet(new_content)
        if not ok:
            return ok, msg

        path = Path(filepath)
        if not path.suffix == ".py":
            return True, "non-python file — syntax-only skip"

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as tmp:
            tmp.write(new_content)
            tmp_path = tmp.name

        try:
            compiled = compileall.compile_file(tmp_path, quiet=1)
            if not compiled:
                return False, "compile failed"
            return True, "compile ok"
        finally:
            Path(tmp_path).unlink(missing_ok=True)