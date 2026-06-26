#!/usr/bin/env python3
"""
🕵 NEURO-SWARM: deterministic tool router.

LLM decision-making removed. Routing is purely keyword based.
"""
import asyncio
import json
import re
import subprocess
import os
import time
from telegram import Bot

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PAYLOADS = os.environ.get("PAYLOADS_DIR", "/usr/share/wordlists")
MEMORY_FILE = os.path.expanduser("~/.prometheus_brain.json")

GREETINGS = {"hi", "hello", "hey", "alive", "sup", "yo"}


def route(task: str):
    """Deterministic route based on keyword matching."""
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


def act(action: str, task: str) -> str:
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


def save_memory(key, val):
    try:
        data = json.load(open(MEMORY_FILE)) if os.path.exists(MEMORY_FILE) else {}
        data[key] = {"val": val, "time": time.time()}
        json.dump(data, open(MEMORY_FILE, "w"), indent=2)
    except Exception:
        pass


async def main():
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN not set — neuro_swarm disabled.")
        return

    bot = Bot(token=TOKEN)
    offset = None
    print("Neuro-Swarm ready!")

    while True:
        try:
            updates = await bot.get_updates(timeout=30, offset=offset)

            for u in updates:
                offset = u.update_id + 1
                if not u.message:
                    continue

                txt = u.message.text.strip()
                cid = u.message.chat.id
                print(f"-> {txt}")

                action, reply = route(txt)
                act_result = act(action, txt)
                save_memory(f"req_{time.time()}", {"task": txt, "action": action})

                if len(act_result) > 500:
                    await bot.send_message(cid, f"```{act_result[:2200]}```", parse_mode="MarkdownV2")
                else:
                    await bot.send_message(cid, act_result)

        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception:
            print("Restarting...")
            asyncio.sleep(3)
