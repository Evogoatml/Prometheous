#!/usr/bin/env python3
"""
SwarmAI Orchestrator
Deploys multiple specialized agent bots that work together as a swarm
"""

import os
import sys
import json
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from prometheus.core.init_dual_brain import initialize_dual_brain

# At startup
dual_brain = initialize_dual_brain(orchestrator=None)

from prometheus.llm.client import LLMClient

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

llm = LLMClient()
_histories: Dict[int, list] = {}


@dataclass
class AgentBot:
    id: str
    name: str
    specialty: str
    capabilities: List[str]
    active: bool = False
    tasks_completed: int = 0
    last_active: float = 0


class SwarmNode:
    def __init__(self, node_id: str, role: str, specialty: str, capabilities: List[str]):
        self.id = node_id
        self.role = role
        self.specialty = specialty
        self.capabilities = capabilities
        self.active = False
        self.tasks_completed = 0
        self.last_active = 0.0

    def process(self, task: str) -> str:
        return f"[{self.role}] Processing: {task[:50]}..."


class SwarmAI:
    def __init__(self, swarm_id: str = "pentest-swarm"):
        self.swarm_id = swarm_id
        self.nodes: Dict[str, SwarmNode] = {}
        self.active_agents: List[str] = []
        self.task_queue: List[Dict] = []
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
            self.nodes[agent_id] = SwarmNode(agent_id, name, specialty, caps)
        logger.info(f"Initialized swarm with {len(self.nodes)} agents")

    def deploy(self, agent_id: str = None) -> Dict:
        with self._lock:
            if agent_id and agent_id in self.nodes:
                node = self.nodes[agent_id]
                node.active = True
                node.last_active = time.time()
                if agent_id not in self.active_agents:
                    self.active_agents.append(agent_id)
                return {"status": "deployed", "agent": node.role, "specialty": node.specialty}

            deployed = []
            for nid, node in self.nodes.items():
                node.active = True
                node.last_active = time.time()
                deployed.append(node.role)
                if nid not in self.active_agents:
                    self.active_agents.append(nid)
            return {"status": "deployed", "count": len(deployed), "agents": deployed}

    def recall(self, agent_id: str = None) -> Dict:
        with self._lock:
            if agent_id and agent_id in self.nodes:
                node = self.nodes[agent_id]
                node.active = False
                if agent_id in self.active_agents:
                    self.active_agents.remove(agent_id)
                return {"status": "recalled", "agent": node.role}

            for nid, node in self.nodes.items():
                node.active = False
            self.active_agents.clear()
            return {"status": "recalled", "count": len(self.nodes)}

    def dispatch_task(self, task: str) -> Dict:
        intent_map = {
            "scanner": "scanner",
            "recon":   "recon",
            "exploit": "exploit",
        }
        try:
            classified = llm.classify_intent(task)
            intent = classified.get("intent", "scanner")
            selected = intent_map.get(intent)
            if not selected:
                selected = self._keyword_fallback(task)
            logger.info(f"LLM classified intent={intent} → agent={selected}")
        except Exception as e:
            logger.warning(f"LLM classify failed, falling back to keyword: {e}")
            selected = self._keyword_fallback(task)

        with self._lock:
            node = self.nodes.get(selected, self.nodes["scanner"])
            node.active = True
            node.last_active = time.time()
            node.tasks_completed += 1
            return {
                "status": "executing",
                "agent": node.role,
                "specialty": node.specialty,
                "task": task[:100]
            }

    def _keyword_fallback(self, task: str) -> str:
        t = task.lower()
        if any(w in t for w in ["scan", "vuln", "cve"]):       return "scanner"
        if any(w in t for w in ["recon", "info", "gather"]):   return "recon"
        if any(w in t for w in ["exploit", "hack", "attack"]):  return "exploit"
        if any(w in t for w in ["privesc", "privilege", "root"]): return "privesc"
        if any(w in t for w in ["persist", "backdoor"]):        return "persistence"
        if any(w in t for w in ["pivot", "lateral"]):           return "pivot"
        if any(w in t for w in ["exfil", "upload"]):            return "exfil"
        if any(w in t for w in ["report", "document"]):         return "report"
        return "scanner"

    def execute_swarm(self, task: str) -> List[Dict]:
        t = task.lower()
        if any(w in t for w in ["full", "complete", "all"]):
            return [{"agent": n.role, "specialty": n.specialty, "status": "completed", "capabilities": n.capabilities}
                    for n in self.nodes.values()]
        return [self.dispatch_task(task)]

    def get_status(self) -> Dict:
        return {
            "swarm_id": self.swarm_id,
            "total_agents": len(self.nodes),
            "active": len([n for n in self.nodes.values() if n.active]),
            "agents": {
                nid: {
                    "role": n.role,
                    "specialty": n.specialty,
                    "active": n.active,
                    "tasks": n.tasks_completed
                }
                for nid, n in self.nodes.items()
            }
        }


swarm = SwarmAI()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = swarm.get_status()
    keyboard = [
        [InlineKeyboardButton("🚀 Deploy All",      callback_data="swarm_deploy")],
        [InlineKeyboardButton("📡 Deploy Scanner",  callback_data="agent_scanner")],
        [InlineKeyboardButton("🔍 Deploy Recon",    callback_data="agent_recon")],
        [InlineKeyboardButton("💥 Deploy Exploit",  callback_data="agent_exploit")],
        [InlineKeyboardButton("⬆ Deploy PrivEsc",  callback_data="agent_privesc")],
        [InlineKeyboardButton("📊 Swarm Status",    callback_data="swarm_status")],
        [InlineKeyboardButton("🔄 Recall All",      callback_data="swarm_recall")],
    ]
    await update.message.reply_text(
        f"<b>🕷 SwarmAI Orchestrator</b>\n\nSwarm: {status['swarm_id']}\nTotal Agents: {status['total_agents']}\nActive: {status['active']}\n\nSelect agent to deploy:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = swarm.get_status()
    text = "<b>🕷 SwarmAI Help</b>\n\n<b>Agents:</b>\n"
    for aid, info in status['agents'].items():
        active = "🟢" if info['active'] else "⚪"
        text += f"{active} {info['role']}: {info['specialty']} (tasks: {info['tasks']})\n"
    text += "\n<b>Commands:</b>\n/start - Deploy menu\n/deploy - Deploy all\n/deploy <agent> - Deploy specific\n/recall - Recall all\n/execute <task> - Run task\n/status - Swarm status\n/agents - List agents"
    await update.message.reply_text(text, parse_mode='HTML')


async def deploy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = context.args[0].lower() if context.args else None
    result = swarm.deploy(agent)
    await update.message.reply_text(f"<b>Deployed:</b> {json.dumps(result)}", parse_mode='HTML')


async def recall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = swarm.recall()
    await update.message.reply_text(f"<b>Recalled:</b> {json.dumps(result)}", parse_mode='HTML')


async def execute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /execute <task>")
        return

    task = ' '.join(context.args)
    await update.message.reply_text(f"🤔 Executing: {task}...")

    result = swarm.dispatch_task(task)
    chat_id = update.message.chat_id
    history = _histories.setdefault(chat_id, [])

    try:
        plan = llm.plan_task(goal=task, target=result.get("task", ""))
        answer = f"<b>Agent:</b> {result.get('agent')}\n<b>Specialty:</b> {result.get('specialty')}\n\n<b>Plan:</b>\n"
        for step in plan.get("steps", []):
            answer += f"• [{step.get('tool')}] {step.get('command')} — {step.get('reason')}\n"
        answer += f"\n<b>Summary:</b> {plan.get('summary', '')}"
    except Exception as e:
        logger.error(f"LLM plan_task failed: {e}")
        answer = f"<b>Agent:</b> {result.get('agent')}\n<b>Specialty:</b> {result.get('specialty')}\n<b>Status:</b> {result.get('status')}"

    history.append({"role": "user", "content": task})
    history.append({"role": "assistant", "content": answer})
    if len(history) > 20:
        _histories[chat_id] = history[-20:]

    await update.message.reply_text(answer, parse_mode='HTML')


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = swarm.get_status()
    text = f"<b>🕷 Swarm Status</b>\n\nSwarm: {status['swarm_id']}\nTotal: {status['total_agents']}\nActive: {status['active']}\n\n<b>Agents:</b>\n"
    for aid, info in status['agents'].items():
        active = "🟢" if info['active'] else "⚪"
        text += f"{active} {info['role']}: {info['specialty']} ({info['tasks']} tasks)\n"
    await update.message.reply_text(text, parse_mode='HTML')


async def agents_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = swarm.get_status()
    keyboard = [[InlineKeyboardButton(f"Deploy {info['role']}", callback_data=f"agent_{aid}")]
                for aid, info in status['agents'].items()]
    await update.message.reply_text("<b>Deploy a specific agent:</b>",
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                    parse_mode='HTML')


async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "swarm_deploy":
        result = swarm.deploy()
    elif data == "swarm_recall":
        result = swarm.recall()
    elif data == "swarm_status":
        status = swarm.get_status()
        await query.message.reply_text(f"<b>Status:</b> {status['active']} active / {status['total_agents']}", parse_mode='HTML')
        return
    elif data.startswith("agent_"):
        result = swarm.deploy(data[6:])
    else:
        result = {"error": "Unknown"}

    await query.message.reply_text(f"<b>Result:</b> {json.dumps(result)}", parse_mode='HTML')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if not text or text.startswith('/'):
        return

    chat_id = update.message.chat_id
    await update.message.reply_text("🤔 Processing through swarm...")

    result = swarm.dispatch_task(text)
    logger.info(f"Dispatched to agent={result.get('agent')}")

    history = _histories.setdefault(chat_id, [])
    try:
        answer = llm.chat_response(history, text)
    except Exception as e:
        logger.error(f"LLM chat_response failed: {e}")
        answer = f"Agent {result.get('agent')} ({result.get('specialty')}) ready — LLM unavailable: {e}"

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": answer})
    if len(history) > 20:
        _histories[chat_id] = history[-20:]

    await update.message.reply_text(answer)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_cmd))
    app.add_handler(CommandHandler("deploy",  deploy_cmd))
    app.add_handler(CommandHandler("recall",  recall_cmd))
    app.add_handler(CommandHandler("execute", execute_cmd))
    app.add_handler(CommandHandler("status",  status_cmd))
    app.add_handler(CommandHandler("agents",  agents_cmd))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("SwarmAI Bot starting...")
    app.run_polling()


if __name__ == '__main__':
    main()
