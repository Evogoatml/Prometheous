"""
Fault localization from live tracebacks.
"""
from __future__ import annotations

import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.config import cfg
    ROOT = cfg.ROOT
except Exception:
    ROOT = Path(__file__).resolve().parents[2]


@dataclass
class StackFrame:
    file: str
    line: int
    function: str
    code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "function": self.function,
            "code": self.code,
        }


@dataclass
class FaultReport:
    exc_type: str
    message: str
    frames: List[StackFrame] = field(default_factory=list)
    primary_file: Optional[str] = None
    primary_line: Optional[int] = None
    primary_function: Optional[str] = None
    primary_code: Optional[str] = None
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exc_type": self.exc_type,
            "message": self.message,
            "primary_file": self.primary_file,
            "primary_line": self.primary_line,
            "primary_function": self.primary_function,
            "primary_code": self.primary_code,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "frames": [f.to_dict() for f in self.frames],
        }


class FaultLocalizer:
    """Extract structured fault data from an exception."""

    def localize(
        self,
        exc: BaseException,
        *,
        tb: Optional[str] = None,
    ) -> FaultReport:
        exc_type = type(exc).__name__
        message = str(exc).strip()

        frames: List[StackFrame] = []
        if tb is None and exc.__traceback__ is not None:
            for frame_summary in traceback.extract_tb(exc.__traceback__):
                code = (frame_summary.line or "").strip()
                frames.append(
                    StackFrame(
                        file=frame_summary.filename,
                        line=frame_summary.lineno or 0,
                        function=frame_summary.name or "",
                        code=code,
                    )
                )
        elif tb:
            frames = self._parse_tb_text(tb)

        primary = self._pick_primary_frame(frames)
        report = FaultReport(
            exc_type=exc_type,
            message=message,
            frames=frames,
        )

        if primary:
            report.primary_file = primary.file
            report.primary_line = primary.line
            report.primary_function = primary.function
            report.primary_code = primary.code
            before, after = self._read_context(primary.file, primary.line)
            report.context_before = before
            report.context_after = after

        return report

    def _pick_primary_frame(self, frames: List[StackFrame]) -> Optional[StackFrame]:
        if not frames:
            return None
        root_str = str(ROOT)
        project_frames = [f for f in frames if f.file.startswith(root_str) and "learning/healing" not in f.file]
        if project_frames:
            return project_frames[-1]
        return frames[-1]

    def _read_context(self, filepath: str, line: int, *, radius: int = 3) -> tuple[List[str], List[str]]:
        path = Path(filepath)
        if not path.is_file():
            return [], []
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return [], []
        idx = max(0, line - 1)
        before = lines[max(0, idx - radius):idx]
        after = lines[idx + 1: min(len(lines), idx + 1 + radius)]
        return before, after

    def _parse_tb_text(self, tb: str) -> List[StackFrame]:
        frames: List[StackFrame] = []
        pattern = re.compile(r'File "([^"]+)", line (\d+), in (\w+)')
        for match in pattern.finditer(tb):
            frames.append(
                StackFrame(
                    file=match.group(1),
                    line=int(match.group(2)),
                    function=match.group(3),
                )
            )
        return frames

    def parse_attribute_error(self, message: str) -> Optional[tuple[str, str]]:
        m = re.search(r"'([^']+)' object has no attribute '([^']+)'", message)
        if m:
            return m.group(1), m.group(2)
        return None

    def parse_key_error(self, message: str) -> Optional[str]:
        m = re.search(r"^['\"]([^'\"]+)['\"]$", message)
        return m.group(1) if m else None

    def parse_module_not_found(self, message: str) -> Optional[str]:
        m = re.search(r"No module named '([^']+)'", message)
        return m.group(1) if m else None