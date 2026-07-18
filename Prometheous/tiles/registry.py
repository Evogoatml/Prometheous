# tiles/registry.py - Prometheous specialist tiles
from typing import Dict, Any

from agents.agent_k import AgentKExecutor
from agents.agentgpt_agent import AgentGPTAgent
from agents.crewai_agent import CrewAISpecialist
from agents.superagi_agent import SuperAGIAgent
from agents.swarms_agent import SwarmsSpecialist

# Pull in growth tiles so those files get used
try:
    from tiles.growth.self_evolving_agent import SelfEvolvingAgent
except Exception:
    SelfEvolvingAgent = None

try:
    from tiles.growth.learning_agent import LearningTile, learn_topic  # noqa: F401
    GrowthLearning = LearningTile
except Exception:
    GrowthLearning = None


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

        if SelfEvolvingAgent:
            self.register("self_evolving", SelfEvolvingAgent())
        if GrowthLearning:
            self.register("growth_learning", GrowthLearning())

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