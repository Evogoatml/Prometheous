"""
Patch proposal generator — produces real diffs, never applies them.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from learning.healing.analyzer import FaultLocalizer, FaultReport, ROOT


@dataclass
class PatchProposal:
    strategy: str
    description: str
    file: Optional[str]
    line: Optional[int]
    original: str
    patched: str
    diff: str
    confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "description": self.description,
            "file": self.file,
            "line": self.line,
            "original": self.original,
            "patched": self.patched,
            "diff": self.diff,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }


class PatchGenerator:
    """Rule-based patch proposals keyed by exception type."""

    STRATEGIES = (
        "attribute_guard",
        "dict_get",
        "none_guard",
        "import_fix",
        "path_guard",
        "index_guard",
        "generic_try_except",
    )

    def __init__(self) -> None:
        self._localizer = FaultLocalizer()

    def generate(
        self,
        fault: FaultReport,
        *,
        preferred_strategy: Optional[str] = None,
    ) -> List[PatchProposal]:
        handlers = {
            "AttributeError": self._attribute_guard,
            "KeyError": self._dict_get,
            "TypeError": self._none_guard,
            "ModuleNotFoundError": self._import_fix,
            "ImportError": self._import_fix,
            "FileNotFoundError": self._path_guard,
            "IndexError": self._index_guard,
        }

        proposals: List[PatchProposal] = []
        handler = handlers.get(fault.exc_type)
        if handler:
            proposals.extend(handler(fault))

        if preferred_strategy:
            proposals.sort(
                key=lambda p: (0 if p.strategy == preferred_strategy else 1, -p.confidence),
            )
        else:
            proposals.sort(key=lambda p: -p.confidence)

        if not proposals and fault.primary_code:
            proposals.append(self._generic_wrapper(fault))

        return proposals

    def _make_proposal(
        self,
        fault: FaultReport,
        *,
        strategy: str,
        description: str,
        original: str,
        patched: str,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PatchProposal:
        diff = "\n".join(
            difflib.unified_diff(
                original.splitlines(),
                patched.splitlines(),
                fromfile=fault.primary_file or "source",
                tofile=f"{fault.primary_file or 'source'} (proposed)",
                lineterm="",
            )
        )
        return PatchProposal(
            strategy=strategy,
            description=description,
            file=fault.primary_file,
            line=fault.primary_line,
            original=original,
            patched=patched,
            diff=diff,
            confidence=confidence,
            metadata=metadata or {},
        )

    def _attribute_guard(self, fault: FaultReport) -> List[PatchProposal]:
        parsed = self._localizer.parse_attribute_error(fault.message)
        if not parsed or not fault.primary_code:
            return []
        obj_t, attr = parsed
        line = fault.primary_code
        indent = line[: len(line) - len(line.lstrip())]

        if f".{attr}" in line:
            patched_line = re.sub(
                rf"(\w+)\.{re.escape(attr)}\b",
                rf"getattr(\1, '{attr}', None)",
                line,
                count=1,
            )
            if patched_line != line:
                return [
                    self._make_proposal(
                        fault,
                        strategy="attribute_guard",
                        description=f"Replace .{attr} with getattr(..., None) on failing line",
                        original=line,
                        patched=patched_line,
                        confidence=0.82,
                        metadata={"attr": attr, "obj_type": obj_t},
                    )
                ]

        guard = (
            f"{indent}if hasattr(obj, '{attr}'):\n"
            f"{indent}    {line.strip()}\n"
            f"{indent}else:\n"
            f"{indent}    raise AttributeError('guard: missing {attr}') from None"
        )
        return [
            self._make_proposal(
                fault,
                strategy="attribute_guard",
                description=f"Wrap failing access to '{attr}' with hasattr guard",
                original=line,
                patched=guard,
                confidence=0.65,
                metadata={"attr": attr},
            )
        ]

    def _dict_get(self, fault: FaultReport) -> List[PatchProposal]:
        key = self._localizer.parse_key_error(fault.message)
        line = fault.primary_code or ""
        if not key or not line:
            return []

        bracket = None
        for pattern in (
            rf'(\w+)\[{re.escape(repr(key))}\]',
            rf'(\w+)\["{re.escape(key)}"\]',
            rf"(\w+)\['{re.escape(key)}'\]",
            rf"(\w+)\[{re.escape(key)}\]",
        ):
            bracket = re.search(pattern, line)
            if bracket:
                break
        if bracket:
            var = bracket.group(1)
            patched = re.sub(
                rf"{re.escape(var)}\[[^\]]+\]",
                f"{var}.get({key!r})",
                line,
                count=1,
            )
            if patched != line:
                return [
                    self._make_proposal(
                        fault,
                        strategy="dict_get",
                        description=f"Use .get({key!r}) instead of KeyError-prone subscript",
                        original=line,
                        patched=patched,
                        confidence=0.85,
                        metadata={"key": key},
                    )
                ]
        return []

    def _none_guard(self, fault: FaultReport) -> List[PatchProposal]:
        line = fault.primary_code or ""
        if not line or "NoneType" not in fault.message:
            return []

        indent = line[: len(line) - len(line.lstrip())]
        target = line.strip()
        guard = (
            f"{indent}if value is not None:\n"
            f"{indent}    {target}\n"
            f"{indent}else:\n"
            f"{indent}    raise TypeError('guard: value was None') from None"
        )
        return [
            self._make_proposal(
                fault,
                strategy="none_guard",
                description="Guard failing line with None check before subscript/call",
                original=line,
                patched=guard,
                confidence=0.7,
                metadata={"pattern": "NoneType"},
            )
        ]

    def _import_fix(self, fault: FaultReport) -> List[PatchProposal]:
        module = self._localizer.parse_module_not_found(fault.message)
        if not module:
            return []

        proposals: List[PatchProposal] = []
        local_match = self._find_local_module(module)
        line = fault.primary_code or f"import {module}"

        if local_match:
            rel_import = local_match.replace("/", ".").removesuffix(".py")
            if rel_import.endswith(".__init__"):
                rel_import = rel_import[: -len(".__init__")]
            patched = f"from {rel_import} import <symbol>  # local module at {local_match}"
            proposals.append(
                self._make_proposal(
                    fault,
                    strategy="import_fix",
                    description=f"Local module exists at {local_match} — fix import path",
                    original=line,
                    patched=patched,
                    confidence=0.75,
                    metadata={"module": module, "local_path": local_match},
                )
            )

        patched_install = (
            f"# missing dependency: {module}\n"
            f"# pip install {module.split('.')[0]}\n"
            f"import {module}"
        )
        proposals.append(
            self._make_proposal(
                fault,
                strategy="import_fix",
                description=f"Install package providing '{module}' or vendor it under project",
                original=line,
                patched=patched_install,
                confidence=0.6,
                metadata={"module": module, "pip_hint": module.split(".")[0]},
            )
        )
        return proposals

    def _find_local_module(self, module: str) -> Optional[str]:
        parts = module.split(".")
        candidates = [
            ROOT / "/".join(parts),
            ROOT / f"{'/'.join(parts)}.py",
            ROOT / parts[0] / "__init__.py",
        ]
        for base in (ROOT / "agents", ROOT / "core", ROOT / "learning", ROOT / "knowledge"):
            candidates.append(base / f"{parts[-1]}.py")
        for cand in candidates:
            if cand.is_file():
                try:
                    return str(cand.relative_to(ROOT))
                except ValueError:
                    return str(cand)
        return None

    def _path_guard(self, fault: FaultReport) -> List[PatchProposal]:
        line = fault.primary_code or ""
        m = re.search(r"\[Errno 2\].*'([^']+)'", fault.message)
        if not m:
            m = re.search(r"'([^']+)'", fault.message)
        missing = m.group(1) if m else "path"

        indent = line[: len(line) - len(line.lstrip())] if line else ""
        guard = (
            f"{indent}from pathlib import Path\n"
            f"{indent}_p = Path({missing!r})\n"
            f"{indent}if not _p.exists():\n"
            f"{indent}    raise FileNotFoundError(f'missing: {{_p}}') from None\n"
            f"{indent}{line.strip() if line else 'open(_p)'}"
        )
        return [
            self._make_proposal(
                fault,
                strategy="path_guard",
                description=f"Check Path({missing!r}).exists() before file access",
                original=line or f"open('{missing}')",
                patched=guard,
                confidence=0.78,
                metadata={"path": missing},
            )
        ]

    def _index_guard(self, fault: FaultReport) -> List[PatchProposal]:
        line = fault.primary_code or ""
        if not line:
            return []
        indent = line[: len(line) - len(line.lstrip())]
        guard = (
            f"{indent}if 0 <= index < len(seq):\n"
            f"{indent}    {line.strip()}\n"
            f"{indent}else:\n"
            f"{indent}    raise IndexError('guard: index out of range') from None"
        )
        return [
            self._make_proposal(
                fault,
                strategy="index_guard",
                description="Bounds-check sequence index before access",
                original=line,
                patched=guard,
                confidence=0.72,
            )
        ]

    def _generic_wrapper(self, fault: FaultReport) -> PatchProposal:
        line = fault.primary_code or "pass"
        indent = line[: len(line) - len(line.lstrip())]
        wrapped = (
            f"{indent}try:\n"
            f"{indent}    {line.strip()}\n"
            f"{indent}except {fault.exc_type} as exc:\n"
            f"{indent}    logger.error('%s', exc)\n"
            f"{indent}    raise"
        )
        return self._make_proposal(
            fault,
            strategy="generic_try_except",
            description=f"Log and re-raise {fault.exc_type} at fault site",
            original=line,
            patched=wrapped,
            confidence=0.4,
        )