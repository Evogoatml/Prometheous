
from importlib import import_module
import asyncio
from brain.autonode_engine import AutoNodeEngine
from importlib import import_module
from llm_client import call_llm
from brain.embedding_memory import EmbeddingMemory

class AutoNodeAdapter:
    def __init__(self):
        self.memory = EmbeddingMemory()

    def run_sequence(self, sequence):
        logs = []
        for step in sequence:
            step = step.strip().lower()

            if step == "analyze":
                logs.append("[AutoNode] Analyzing input context…")
                # pretend to analyze prior reasoning
                analysis = "Pattern detected in reasoning chain."
                self.memory.store("system", step, analysis)
                logs.append(analysis)

            elif step == "summarize":
                logs.append("[AutoNode] Summarizing stored context…")
                summary = call_llm("Summarize key logic insights.")
                self.memory.store("system", step, summary)
                logs.append(summary)

            elif step == "store":
                logs.append("[AutoNode] Finalizing and storing session memory…")
                self.memory.store("system", "final", "Session data persisted.")
                logs.append("Session persisted to memory.")

            else:
                logs.append(f"[AutoNode] Unknown step: {step}")

        return "\n".join(logs)

    def learn_from_execution(self, feedback):
        self.engine.memory.append(feedback)
        return f"[AutoNode] Learned from feedback: {feedback}"
