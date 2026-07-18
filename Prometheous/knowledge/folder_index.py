"""
On-demand folder context for Prometheous.

Indexes a single folder when asked — no repo-wide AGENT.md generation.
Cache lives under data/folder_index/ (not .backend/ at repo root).
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

try:
    from utils.config import cfg
    ROOT = cfg.ROOT
    CACHE_DIR = cfg.DATA_DIR / "folder_index"
except Exception:
    ROOT = Path(__file__).resolve().parents[1]
    CACHE_DIR = ROOT / "data" / "folder_index"

DEFAULT_EXCLUDE_DIRS: Set[str] = {
    ".git", ".backend", "__pycache__", "node_modules",
    ".venv", "venv", ".idea", "htmlcov", ".coverage",
    "target", ".grok", ".logs",
}

DEFAULT_EXTENSIONS: Set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".txt", ".md", ".yaml", ".yml",
    ".toml", ".csv", ".html", ".css", ".rs",
    ".sh", ".env.example",
}


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def resolve_folder(path: str, *, root: Optional[Path] = None) -> Path:
    """Resolve a folder inside the project root; reject path traversal."""
    base = (root or ROOT).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path must stay under project root: {base}") from exc

    if not candidate.exists():
        raise FileNotFoundError(f"folder not found: {candidate}")
    if not candidate.is_dir():
        raise NotADirectoryError(f"not a directory: {candidate}")
    return candidate


def _file_hash(filepath: Path, max_bytes: int = 256_000) -> Optional[str]:
    hasher = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            hasher.update(f.read(max_bytes))
        return hasher.hexdigest()[:16]
    except OSError:
        return None


def _folder_fingerprint(folder: Path, exclude_dirs: Set[str], extensions: Set[str]) -> str:
    parts: List[str] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for name in sorted(filenames):
            if extensions and Path(name).suffix not in extensions:
                continue
            fp = Path(dirpath) / name
            try:
                stat = fp.stat()
            except OSError:
                continue
            parts.append(f"{fp.relative_to(folder)}:{stat.st_mtime_ns}:{stat.st_size}")
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def scan_folder(
    path: str,
    *,
    root: Optional[Path] = None,
    recursive: bool = True,
    max_depth: int = 4,
    max_files: int = 200,
    extensions: Optional[Iterable[str]] = None,
    exclude_dirs: Optional[Iterable[str]] = None,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Scan one folder and return structured context.

    Only walks under the requested folder — never the whole repo.
    """
    base = (root or ROOT).resolve()
    folder = resolve_folder(path, root=base)
    ext_set = set(extensions) if extensions else DEFAULT_EXTENSIONS
    skip_dirs = set(exclude_dirs) if exclude_dirs else set(DEFAULT_EXCLUDE_DIRS)

    fingerprint = _folder_fingerprint(folder, skip_dirs, ext_set)
    cache_key = hashlib.md5(str(folder).encode()).hexdigest()[:12]
    cache_path = _ensure_cache_dir() / f"{cache_key}.json"

    if use_cache and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                cached["from_cache"] = True
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    files: Dict[str, Dict[str, Any]] = {}
    files_by_ext: Dict[str, List[str]] = defaultdict(list)
    count = 0

    for dirpath, dirnames, filenames in os.walk(folder):
        rel_dir = Path(dirpath).relative_to(folder)
        depth = 0 if str(rel_dir) == "." else len(rel_dir.parts)
        if not recursive and depth > 0:
            dirnames.clear()
            continue
        if depth >= max_depth:
            dirnames.clear()

        dirnames[:] = sorted(d for d in dirnames if d not in skip_dirs)

        for name in sorted(filenames):
            if count >= max_files:
                break
            if extensions and Path(name).suffix not in ext_set:
                continue

            fp = Path(dirpath) / name
            try:
                stat = fp.stat()
            except OSError:
                continue

            rel = str(fp.relative_to(folder))
            entry = {
                "path": rel,
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "extension": fp.suffix or "",
                "hash": _file_hash(fp),
            }
            files[rel] = entry
            files_by_ext[entry["extension"] or "(none)"].append(rel)
            count += 1

        if count >= max_files:
            break

    total_size = sum(m["size"] for m in files.values())
    result: Dict[str, Any] = {
        "status": "ok",
        "folder": str(folder),
        "folder_rel": str(folder.relative_to(base)) if folder != base else ".",
        "folder_name": folder.name,
        "scanned_at": datetime.now().isoformat(),
        "fingerprint": fingerprint,
        "file_count": len(files),
        "total_size": total_size,
        "truncated": count >= max_files,
        "extensions": {ext: len(names) for ext, names in sorted(files_by_ext.items())},
        "files": files,
        "from_cache": False,
    }

    try:
        cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    except OSError:
        pass

    return result


def format_folder_summary(ctx: Dict[str, Any], *, max_lines: int = 30) -> str:
    """Human-readable summary for Telegram / CLI."""
    if ctx.get("status") != "ok":
        return ctx.get("error", "folder context unavailable")

    lines = [
        f"📁 {ctx.get('folder_rel', ctx.get('folder_name', '?'))}",
        f"Files: {ctx.get('file_count', 0)}"
        + (" (truncated)" if ctx.get("truncated") else ""),
    ]

    total = ctx.get("total_size", 0)
    if total >= 1024 * 1024:
        lines.append(f"Size: {total / 1024 / 1024:.2f} MB")
    else:
        lines.append(f"Size: {total / 1024:.1f} KB")

    exts = ctx.get("extensions") or {}
    if exts:
        ext_line = ", ".join(f"{k} ({v})" for k, v in sorted(exts.items(), key=lambda x: -x[1])[:8])
        lines.append(f"Types: {ext_line}")

    files = ctx.get("files") or {}
    shown = 0
    for rel in sorted(files.keys()):
        if shown >= max_lines:
            lines.append(f"…and {len(files) - shown} more")
            break
        meta = files[rel]
        size = meta.get("size", 0)
        size_s = f"{size / 1024:.1f}KB" if size >= 1024 else f"{size}B"
        lines.append(f"• {rel} ({size_s})")
        shown += 1

    if ctx.get("from_cache"):
        lines.append("(cached)")
    return "\n".join(lines)


def search_folders(query: str, *, root: Optional[Path] = None, limit: int = 10) -> List[Dict[str, Any]]:
    """Find project folders whose name or path matches query."""
    base = (root or ROOT).resolve()
    q = query.lower().strip()
    if not q:
        return []

    hits: List[Dict[str, Any]] = []
    for dirpath, dirnames, _ in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDE_DIRS]
        rel = Path(dirpath).relative_to(base)
        parts = [p.lower() for p in rel.parts]
        name = Path(dirpath).name.lower()
        if q in name or any(q in p for p in parts):
            hits.append({
                "path": str(Path(dirpath).relative_to(base)),
                "name": Path(dirpath).name,
            })
        if len(hits) >= limit:
            break
    return hits