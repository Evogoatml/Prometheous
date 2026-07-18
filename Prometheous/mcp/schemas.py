"""
MCP tool schemas — single source for function-calling metadata.
"""
from __future__ import annotations

from typing import Any, Dict, List

try:
    from utils.config import cfg
    ROOT = str(cfg.ROOT)
except Exception:
    ROOT = ""

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "tools.list",
        "description": "List available MCP tools and parameter schemas",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "ping",
        "description": "Health check the MCP tool layer",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "fs.exists",
        "description": "Check whether a file or path exists",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Absolute or project-relative path"}},
            "required": ["path"],
        },
    },
    {
        "name": "fs.read",
        "description": "Read a text file (truncated)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 200000},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs.write",
        "description": "Write a text file under the project root (creates parents)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or project-relative path"},
                "text": {"type": "string", "description": "File contents"},
                "mode": {"type": "string", "default": "w"},
            },
            "required": ["path", "text"],
        },
    },
    {
        "name": "fs.folder_context",
        "description": "Index one project folder (file list + sizes)",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_files": {"type": "integer", "default": 200},
            },
            "required": ["path"],
        },
    },
    {
        "name": "web.search",
        "description": "Web search via DuckDuckGo or SerpAPI",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "num_results": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "http.get",
        "description": "Fetch a URL (http/https)",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_bytes": {"type": "integer", "default": 200000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "shell.run",
        "description": "Run an allow-listed shell command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "default": ROOT},
            },
            "required": ["command"],
        },
    },
    {
        "name": "healing.list",
        "description": "List recent self-healing proposals",
        "parameters": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 5}},
            "required": [],
        },
    },
    {
        "name": "github.search",
        "description": "Search GitHub repositories",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "github.readme",
        "description": "Fetch a GitHub repository README",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["owner", "repo"],
        },
    },
    {
        "name": "github.file",
        "description": "Read a file from a GitHub repository",
        "parameters": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "ref": {"type": "string", "default": ""},
            },
            "required": ["owner", "repo", "path"],
        },
    },
    {
        "name": "hf.search_models",
        "description": "Search Hugging Face models",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "hf.search_datasets",
        "description": "Search Hugging Face datasets",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "hf.pull_dataset",
        "description": "Pull a small dataset slice into data/external/huggingface",
        "parameters": {
            "type": "object",
            "properties": {
                "dataset_id": {"type": "string"},
                "split": {"type": "string", "default": "train"},
                "max_rows": {"type": "integer", "default": 50},
            },
            "required": ["dataset_id"],
        },
    },
]

SCHEMA_BY_NAME: Dict[str, Dict[str, Any]] = {t["name"]: t for t in TOOL_SCHEMAS}


def list_tool_schemas() -> List[Dict[str, Any]]:
    return list(TOOL_SCHEMAS)


def openai_tools_payload() -> List[Dict[str, Any]]:
    """OpenAI / Grok function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["parameters"],
            },
        }
        for s in TOOL_SCHEMAS
    ]