# self_evolving_agent.py
# Autonomous decision-making and dynamic code generation removed.
# This layer now only executes deterministic tasks supplied by the user.
import os
import json
import time
import tempfile
from typing import Dict, List, Any


class SelfEvolvingAgent:
    def __init__(self, name="NeuroForge"):
        self.name = name
        self.session_dir = tempfile.mkdtemp(prefix="agent_memory_")

    def run(self):
        print(f"\n{self.name} — deterministic mode. No LLM decisions.")
        print("Send task text (or 'exit' to quit):")
        while True:
            goal = input("\nuser> ").strip()
            if goal.lower() in ("exit", "quit"):
                break
            result = {"status": "ok", "goal": goal, "note": "auto-execution disabled"}
            path = os.path.join(self.session_dir, f"task_{int(time.time())}.json")
            with open(path, "w") as f:
                json.dump(result, f, indent=2)
            print(f"Saved -> {path}")


if __name__ == "__main__":
    agent = SelfEvolvingAgent("NeuroForge")
    agent.run()
