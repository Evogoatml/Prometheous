# prometheus/tiles/registry.py
from typing import Dict, Any

from prometheus.agents.agent_k import AgentKExecutor
from prometheus.agents.agentgpt_agent import AgentGPTAgent
from prometheus.agents.crewai_agent import CrewAISpecialist
from prometheus.agents.superagi_agent import SuperAGIAgent
from prometheus.agents.swarms_agent import SwarmsSpecialist


class TileRegistry:

    def __init__(self):
        self._tiles = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register("agentk", AgentKExecutor())
        self.register("agentgpt", AgentGPTAgent())
        self.register("crewai", CrewAISpecialist())
        self.register("superagi", SuperAGIAgent())
        self.register("swarms", SwarmsSpecialist())

    def register(self, name: str, tile):
        self._tiles[name] = tile
        return self

    def get(self, name: str):
        return self._tiles.get(name)

    def list(self) -> list:
        return list(self._tiles.keys())

    async def execute(self, name: str, task: Dict) -> Dict:
        tile = self.get(name)
        if not tile:
            return {"error": f"Tile '{name}' not found"}
        return await tile.execute(task)