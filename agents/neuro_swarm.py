#!/usr/bin/env python3
"""
Neuro-Swarm Agent

Deterministic tool router registered with the central SwarmOrchestrator.
No standalone Telegram bot.
"""
import os
import json
import re
import subprocess
import time
from typing import Any, Dict

from swarm.base import BaseAgent
from swarm.orchestrator import orb

PAYLOADS = os.environ.get("PAYLOADS_DIR", "/usr/share/wordlists")
MEMORY_FILE = os.path.expanduser("~/.prometheus_brain.json")

GREETINGS = {"hi", "hello", "hey", "alive", "sup", "yo"}


def _route(task: str):
    task_lower = task.lower()
    if any(g in task_lower for g in GREETINGS):
        return "greeting", "Hey! What do you need? Send URL or request tool."
    if any(k in task_lower for k in ("find", "payload")):
        return "search_payloads", "Found matching folders"
    if "nmap" in task_lower:
        return "nmap_scan", "Running nmap"
    if any(k in task_lower for k in ("gobuster", "dir")):
        return "gobuster", "Running gobuster"
    if "sqlmap" in task_lower:
        return "sqlmap", "Running sqlmap"
    return "chat", "I can run nmap, gobuster, sqlmap. Send URL!"


def _act(action: str, task: str) -> str:
    parts = task.split()
    urls = re.findall(r'([a-z0-9.-]+\.[a-z]{2,})', task.lower())
    target = urls[0] if urls else None

    if action == "nmap_scan" and target:
        r = subprocess.run(f"nmap -sV {target}", shell=True, capture_output=True, text=True, timeout=45)
        return r.stdout[:2000] if r.stdout else "No output"
    if action == "gobuster" and target:
        r = subprocess.run(
            f"gobuster dir -u http://{target} -w /usr/share/wordlists/dirb/common.txt -q",
            shell=True, capture_output=True, text=True, timeout=45,
        )
        return r.stdout[:1500] if r.stdout else "No output"
    if action == "sqlmap" and target:
        r = subprocess.run(f"sqlmap -u {target} --batch -v 0", shell=True, capture_output=True, text=True, timeout=45)
        return r.stdout[:1500] if r.stdout else "No output"
    if action == "search_payloads" and os.path.isdir(PAYLOADS):
        folders = sorted(d.split("/")[-1] for d in os.listdir(PAYLOADS) if os.path.isdir(f"{PAYLOADS}/{d}"))
        matches = [f for f in folders if any(q in f.lower() for q in parts if len(q) > 2)]
        return ", ".join(matches[:10]) if matches else "No matches"
    if action == "greeting":
        return "Hey! What do you need? Send URL or request tool."
    return "Send a URL or ask for help!"


def _save_memory(key, val):
    try:
        data = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        data[key] = {"val": val, "time": time.time()}
        json.dump(data, open(MEMORY_FILE, "w"), indent=2)
    except Exception:
        pass


class NeuroSwarmAgent(BaseAgent):
    name = "neuro_swarm"
    role = "Neuro Swarm"
    specialty = "Deterministic tool router for nmap/gobuster/sqlmap"
    version = "0.1.0"

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        task = payload.get("task") or payload.get("text") or ""
        action, _ = _route(task)
        output = _act(action, task)
        _save_memory(f"req_{time.time()}", {"task": task, "action": action})
        return {
            "status": "ok",
            "agent": self.name,
            "action": action,
            "result": output,
        }


orb.register(NeuroSwarmAgent())
