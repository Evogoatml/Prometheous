#!/usr/bin/env python3
"""
SwarmAI Orchestrator Agent
"""
import os
import time
import json
import logging
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from swarm.base import BaseAgent
from swarm.orchestrator import orb

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class AgentBot:
    id: str
    name: str
    specialty: str
    capabilities: List[str]
    active: bool = False
    tasks_completed: int = 0
    last_active: float = 0


class _SwarmAI:
    """Internal swarm state container."""
    def __init__(self, swarm_id: str = "pentest-swarm"):
        self.swarm_id = swarm_id
        self.nodes: Dict[str, AgentBot] = {}
        self.active_agents: List[str] = []
        self.results: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._init_swarm()

    def _init_swarm(self):
        agents = [
            ("scanner",     "Scanner",  "Vulnerability scanning",   ["scan", "nmap", "cve"]),
            ("recon",       "Recon",    "Information gathering",     ["whois", "dns", "enum"]),
            ("exploit",     "Exploit",  "Exploitation",              ["metasploit", "shell", "pwn"]),
            ("privesc",     "PrivEsc",  "Privilege escalation",      ["sudo", "kernel", "token"]),
            ("persistence", "Persist",  "Persistence",               ["backdoor", "rootkit", "schedule"]),
            ("pivot",       "Pivot",    "Lateral movement",          ["psexec", "ssh", "wmiconv"]),
            ("exfil",       "Exfil",    "Data exfiltration",         ["upload", "dns", "http"]),
            ("report",      "Report",   "Reporting",                 ["markdown", "json", "html"]),
        ]
        for agent_id, name, specialty, caps in agents:
            self.nodes[agent_id] = AgentBot(agent_id, name, specialty, caps)
        logger.info("Initialized swarm with %s agents", len(self.nodes))

    def deploy(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if agent_id and agent_id in self.nodes:
                node = self.nodes[agent_id]
                node.active = True
                node.last_active = time.time()
                if agent_id not in self.active_agents:
                    self.active_agents.append(agent_id)
                return {"status": "deployed", "agent": node.name, "specialty": node.specialty}
            for node in self.nodes.values():
                node.active = True
                node.last_active = time.time()
                if node.id not in self.active_agents:
                    self.active_agents.append(node.id)
            deployed = [n.name for n in self.nodes.values()]
            return {"status": "deployed", "count": len(deployed), "agents": deployed}

    def recall(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            if agent_id and agent_id in self.nodes:
                node = self.nodes[agent_id]
                node.active = False
                if agent_id in self.active_agents:
                    self.active_agents.remove(agent_id)
                return {"status": "recalled", "agent": node.name}
            for node in self.nodes.values():
                node.active = False
            self.active_agents.clear()
            return {"status": "recalled", "count": len(self.nodes)}

    def dispatch(self, task: str) -> Dict[str, Any]:
        intent_map = {
            "scanner": "scanner", "recon": "recon", "exploit": "exploit",
        }
        selected = next((intent_map[k] for k in intent_map if k in task.lower()), self._keyword_fallback(task))
        with self._lock:
            node = self.nodes.get(selected, self.nodes["scanner"])
            node.active = True
            node.last_active = time.time()
            node.tasks_completed += 1
            return {"status": "executing", "agent": node.name, "specialty": node.specialty, "task": task[:100]}

    def _keyword_fallback(self, task: str) -> str:
        t = task.lower()
        if any(w in t for w in ["scan", "vuln", "cve"]): return "scanner"
        if any(w in t for w in ["recon", "info", "gather"]): return "recon"
        if any(w in t for w in ["exploit", "hack", "attack"]): return "exploit"
        if any(w in t for w in ["privesc", "privilege", "root"]): return "privesc"
        if any(w in t for w in ["persist", "backdoor"]): return "persistence"
        if any(w in t for w in ["pivot", "lateral"]): return "pivot"
        if any(w in t for w in ["exfil", "upload"]): return "exfil"
        if any(w in t for w in ["report", "document"]): return "report"
        return "scanner"

    def execute_swarm(self, task: str) -> List[Dict[str, Any]]:
        if any(w in task.lower() for w in ("full", "complete", "all")):
            return [{"agent": n.name, "specialty": n.specialty, "status": "completed", "capabilities": n.capabilities}
                    for n in self.nodes.values()]
        return [self.dispatch(task)]

    def get_status(self) -> Dict[str, Any]:
        active = sum(1 for n in self.nodes.values() if n.active)
        return {
            "swarm_id": self.swarm_id,
            "total_agents": len(self.nodes),
            "active": active,
            "agents": {
                nid: {"role": n.name, "specialty": n.specialty, "active": n.active, "tasks": n.tasks_completed}
                for nid, n in self.nodes.items()
            },
        }


class SwarmOrchestratorAgent(BaseAgent):
    name = "swarm_orchestrator"
    role = "Swarm Orchestrator"
    specialty = "Deploy and manage pentest swarm agents"
    version = "0.2.0"

    def __init__(self):
        super().__init__()
        self.swarm = _SwarmAI()

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        action = (payload.get("action") or "status").lower()
        task = payload.get("task") or payload.get("text") or ""

        if action in ("deploy", "start"):
            return self.swarm.deploy(payload.get("agent") or payload.get("agent_id"))
        if action in ("recall", "stop"):
            return self.swarm.recall(payload.get("agent") or payload.get("agent_id"))
        if action in ("execute", "run", "dispatch"):
            return self.swarm.dispatch(task)
        if action in ("status",):
            return self.swarm.get_status()
        if any(w in task.lower() for w in ("full", "complete", "all")):
            return {"status": "swarm", "results": self.swarm.execute_swarm(task)}
        return self.swarm.dispatch(task)

    def on_recall(self) -> None:
        super().on_recall()
        for node in self.swarm.nodes.values():
            node.active = False


orb.register(SwarmOrchestratorAgent())
