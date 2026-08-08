import asyncio

class AutoNodeEngine:
    def __init__(self):
        self.memory = []

    async def execute(self, sequence):
        results = []
        for step in sequence:
            await asyncio.sleep(0.3)  # pretend work
            results.append(f"[AutoNodeEngine] Executed: {step}")
            self.memory.append(step)
        return "\n".join(results)

    def recall(self):
        return f"[AutoNodeEngine] Memory: {', '.join(self.memory) or 'empty'}"
