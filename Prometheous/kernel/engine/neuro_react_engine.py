"""NeuroReactCognitiveEngine — OODA-loop orchestrator core."""
import asyncio, json, time, uuid, logging
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from core.reasoning.brain.core import DualBrain
from core.graphrag.engine import GraphRAGEngine
from core.reasoning.brain.knowledge.knowledge_tank import KnowledgeTank

logger = logging.getLogger(__name__)

@dataclass
class Perception:
    source: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)

@dataclass
class Decision:
    decision_id: str
    action_type: str
    target_agent: Optional[str]
    payload: Dict[str, Any]
    reasoning: str
    confidence: float
    timestamp: float = field(default_factory=time.time)

@dataclass
class ActionResult:
    action_id: str
    success: bool
    output: Any
    latency_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class NeuroReactCognitiveEngine:
    def __init__(self, brain: DualBrain, graphrag: GraphRAGEngine,
                 knowledge_tank: KnowledgeTank, config: Optional[Dict] = None):
        self.engine_id = f"neuro-react-{uuid.uuid4().hex[:8]}"
        self.brain = brain; self.graphrag = graphrag; self.knowledge_tank = knowledge_tank
        self.config = config or {}
        self.max_steps = self.config.get("max_steps_per_query", 5)
        self.temperature = self.config.get("temperature", 0.7)
        self.tool_preference: Dict[str, float] = {}
        self.decision_history: List[Decision] = []
        self.result_history: List[ActionResult] = []
        self.logger = logger
        self.logger.info("NeuroReactCognitiveEngine initialized: %s", self.engine_id)

    async def process(self, goal: str, context: Optional[Dict] = None,
                      agents: Optional[Dict[str, Callable]] = None) -> Dict[str, Any]:
        start = time.time()
        session_id = f"session-{uuid.uuid4().hex[:8]}"
        trace: List[Dict[str, Any]] = []
        observation = self._observe(goal, context)
        trace.append({"phase": "OBSERVE", "data": observation})
        orientation = self._orient(goal, observation)
        trace.append({"phase": "ORIENT", "data": orientation})
        steps, step_results = [], []
        for step_idx in range(self.max_steps):
            decision = self._decide(goal, orientation, step_results, step_idx)
            if decision.action_type == "finalize": break
            self.decision_history.append(decision)
            trace.append({"phase": "DECIDE", "step": step_idx, "data": decision.__dict__})
            steps.append(decision)
            if agents and decision.target_agent in agents:
                agent_fn = agents[decision.target_agent]
                act_start = time.time()
                try:
                    if asyncio.iscoroutinefunction(agent_fn):
                        output = await agent_fn(decision.payload)
                    else:
                        output = agent_fn(decision.payload)
                    success = True
                except Exception as e:
                    output = {"error": str(e)}; success = False
                latency = (time.time() - act_start) * 1000
                result = ActionResult(action_id=decision.decision_id, success=success, output=output, latency_ms=latency)
            else:
                result = ActionResult(action_id=decision.decision_id, success=False,
                                      output={"error": f"Agent {decision.target_agent} not found"}, latency_ms=0.0)
            self.result_history.append(result); step_results.append(result)
            trace.append({"phase": "ACT", "step": step_idx, "data": result.__dict__})
            thought_id = self.graphrag.add_node(label=f"Step {step_idx} thought", content=decision.reasoning,
                                                node_type="THOUGHT", metadata={"session": session_id, "goal": goal})
            action_id = self.graphrag.add_node(label=decision.action_type, content=json.dumps(decision.payload),
                                               node_type="ACTION", metadata={"agent": decision.target_agent})
            result_id = self.graphrag.add_node(label=f"Result {step_idx}", content=str(result.output)[:500],
                                               node_type="RESULT", metadata={"success": result.success, "latency": result.latency_ms})
            reward = 1.0 if result.success else -1.0
            reward_id = self.graphrag.add_node(label=f"reward {reward}", content=str(reward),
                                               node_type="REWARD", metadata={"score": reward})
            self.graphrag.add_edge(thought_id, action_id, "TRIGGERS")
            self.graphrag.add_edge(action_id, result_id, "PRODUCES")
            self.graphrag.add_edge(result_id, reward_id, "EVALUATES")
            state_vec = self.brain.neural.encode(goal)
            next_vec = self.brain.neural.encode(str(result.output))
            self.brain.learn(state_vec, decision.action_type, reward, next_vec)
        total_time = (time.time() - start) * 1000
        return {"session_id": session_id, "engine_id": self.engine_id, "goal": goal,
                "summary": self._synthesize(steps, step_results), "steps": len(steps),
                "results": [r.__dict__ for r in step_results], "trace": trace,
                "total_latency_ms": total_time, "brain_state": self.brain.get_state(),
                "timestamp": datetime.utcnow().isoformat()}

    def _observe(self, goal: str, context: Optional[Dict]) -> Dict[str, Any]:
        return {"goal": goal, "context": context,
                "rag_context": self.graphrag.query_context(goal, max_tokens=1500),
                "knowledge_hits": self.knowledge_tank.search(goal, limit=5), "timestamp": time.time()}

    def _orient(self, goal: str, observation: Dict[str, Any]) -> Dict[str, Any]:
        return {"thought": self.brain.think(goal, context=observation),
                "decision": self.brain.decide(reasoning_level="dual"),
                "tags": self.brain._extract_tags(goal)}

    def _decide(self, goal: str, orientation: Dict[str, Any], past_results: List[ActionResult], step_idx: int) -> Decision:
        tags = orientation.get("tags", [])
        past_errors = [r for r in past_results if not r.success]
        if step_idx == 0: action_type, target, reasoning = "gather", "research-1", "First step: gather information."
        elif "scan" in tags or "exploit" in tags: action_type, target, reasoning = "execute", "shell-1", "Security task: dispatch executor."
        elif "research" in tags or "find" in tags: action_type, target, reasoning = "search", "research-1", "Research task: dispatch knowledge retrieval."
        elif past_errors: action_type, target, reasoning = "recover", "supervisor-1", f"Recovering from {len(past_errors)} errors."
        elif step_idx >= self.max_steps - 1: action_type, target, reasoning = "finalize", None, "Final step: synthesizing."
        else: action_type, target, reasoning = "analyze", "analyst-1", "Standard analysis."
        return Decision(decision_id=f"dec-{uuid.uuid4().hex[:6]}", action_type=action_type, target_agent=target,
                        payload={"goal": goal, "step": step_idx, "orientation": orientation},
                        reasoning=reasoning, confidence=orientation["decision"]["confidence"])

    def _synthesize(self, steps: List[Decision], results: List[ActionResult]) -> str:
        ok = sum(1 for r in results if r.success)
        return f"Processed {len(steps)} steps. Success: {ok}/{len(results)}. Last: {str(results[-1].output)[:200] if results else 'N/A'}."

    def get_policy(self) -> Dict[str, Any]:
        return {"max_steps": self.max_steps, "temperature": self.temperature,
                "tool_preference": self.tool_preference, "decision_count": len(self.decision_history)}

    def adjust_policy(self, recent_rewards: List[float]):
        if not recent_rewards: return
        avg = sum(recent_rewards) / len(recent_rewards)
        if avg > 0.8 and self.max_steps < 10: self.max_steps += 1
        elif avg < 0.4 and self.max_steps > 2: self.max_steps -= 1
        logger.info("Policy adjusted: max_steps=%d (avg_reward=%.2f)", self.max_steps, avg)

