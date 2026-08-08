"""
Cognitive Core (Reasoning Engine) - Decision-making and planning
Prometheus Agent - SGE Stack
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

from .logger import setup_logger
from .interface import Intent
from .config import PrometheusConfig

logger = setup_logger(__name__)


@dataclass
class Task:
    """Single task in a plan"""
    id: str
    description: str
    tool_name: Optional[str]
    tool_args: Dict
    dependencies: List[str]
    expected_output: str

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "dependencies": self.dependencies,
            "expected_output": self.expected_output
        }


@dataclass
class Plan:
    """Execution plan"""
    goal: str
    tasks: List[Task]
    reasoning: str
    is_complete: bool

    def to_dict(self) -> Dict:
        return {
            "goal": self.goal,
            "tasks": [t.to_dict() for t in self.tasks],
            "reasoning": self.reasoning,
            "is_complete": self.is_complete
        }


@dataclass
class ExecutionResult:
    """Result of plan execution"""
    plan_id: str
    tasks_completed: List[str]
    tasks_failed: List[str]
    output: str
    is_complete: bool
    error: Optional[str]

    def to_dict(self) -> Dict:
        return {
            "plan_id": self.plan_id,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "output": self.output,
            "is_complete": self.is_complete,
            "error": self.error
        }


@dataclass
class Observation:
    """Reflection observation"""
    summary: str
    success: bool
    lessons_learned: str
    next_steps: Optional[str]
    should_continue: bool

    def to_dict(self) -> Dict:
        return {
            "summary": self.summary,
            "success": self.success,
            "lessons_learned": self.lessons_learned,
            "next_steps": self.next_steps,
            "should_continue": self.should_continue
        }


# ---------------------------------------------------------------------------
# Intent classification labels
# ---------------------------------------------------------------------------

INTENT_CREATE   = "create"
INTENT_SEARCH   = "search"
INTENT_READ     = "read"
INTENT_WRITE    = "write"
INTENT_DELETE   = "delete"
INTENT_EXECUTE  = "execute"
INTENT_ANALYZE  = "analyze"
INTENT_NETWORK  = "network"
INTENT_DATABASE = "database"
INTENT_GENERIC  = "generic"

INTENT_KEYWORDS: Dict[str, List[str]] = {
    INTENT_CREATE:   ["create", "build", "generate", "make", "scaffold", "initialize", "setup", "new"],
    INTENT_SEARCH:   ["search", "find", "query", "look up", "locate", "discover", "scan"],
    INTENT_READ:     ["read", "load", "open", "fetch", "get", "retrieve", "show", "display", "print"],
    INTENT_WRITE:    ["write", "save", "store", "update", "edit", "modify", "append", "insert"],
    INTENT_DELETE:   ["delete", "remove", "drop", "destroy", "clean", "purge", "wipe"],
    INTENT_EXECUTE:  ["run", "execute", "launch", "start", "trigger", "call", "invoke", "process"],
    INTENT_ANALYZE:  ["analyze", "analyse", "inspect", "check", "audit", "review", "evaluate", "assess", "compare"],
    INTENT_NETWORK:  ["request", "download", "upload", "send", "post", "get", "api", "http", "webhook", "ping"],
    INTENT_DATABASE: ["database", "db", "sql", "insert", "select", "table", "record", "migrate", "schema"],
}


class CognitiveCore:
    """
    Cognitive Core - Reasoning Engine

    Purpose: autonomous decision-making and planning for Prometheus Agent.

    Responsibilities:
    - Classify intent from natural language goals
    - Decompose goals into ordered, dependency-aware task graphs
    - Integrate memory context into planning decisions
    - Perform structured reflection after execution
    - Determine continuation or termination of autonomous loops

    All reasoning is native to Prometheus. No external model is delegated
    planning or reflection authority. External model calls are tool calls
    only and do not own any part of the reasoning loop.
    """

    def __init__(self, config: PrometheusConfig):
        self.config = config
        self.logger = setup_logger(__name__)
        self.system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        return """You are Prometheus, an autonomous AI agent operating under the SGE stack.

Identity: Prometheus Agent
Capabilities:
- Understanding and decomposing natural language goals
- Planning ordered, dependency-aware multi-step task graphs
- Executing tools and actions
- Managing memory and cognitive state
- Operating continuously until goals are completed

Behavior:
- Proactive and autonomous
- Break complex goals into clear executable steps
- Use available tools effectively
- Learn from execution results
- Reflect on outcomes and adjust approach
- Communicate clearly about actions taken

Constraints:
- All actions pass through the orchestration layer
- Respect permission boundaries
- Maintain deterministic state tracking
- Log all significant actions
- Never hard-code task logic
- External model calls are tool calls only — they never own the reasoning loop

Planning principles:
1. Analyze the goal carefully before decomposing
2. Build ordered tasks with explicit dependency chains
3. Assign the most appropriate tool to each task
4. Account for validation and error recovery steps
5. Prefer reversible actions where possible

Reflection principles:
1. Assess success against expected outputs, not just completion flags
2. Identify root causes of failures, not just symptoms
3. Determine whether partial results are usable
4. Decide continuation based on state, not assumptions"""

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def plan_actions(
        self,
        intent: Intent,
        context: Dict,
        memory: List[Dict]
    ) -> Plan:
        """
        Decompose an intent into an executable Plan.
        All planning is native to Prometheus.
        """
        self.logger.info(f"Planning actions for: {intent.content[:80]}...")

        intent_type, confidence = self._classify_intent(intent.content)
        memory_hints = self._extract_memory_hints(memory)

        self.logger.info(f"Intent classified as '{intent_type}' (confidence={confidence:.2f})")

        tasks = self._decompose(intent.content, intent_type, context, memory_hints)
        reasoning = self._build_reasoning(intent.content, intent_type, confidence, memory_hints)

        return Plan(
            goal=intent.content,
            tasks=tasks,
            reasoning=reasoning,
            is_complete=False
        )

    async def reflect_on_execution(
        self,
        plan: Plan,
        result: ExecutionResult,
        context: Dict
    ) -> Observation:
        """
        Derive a structured Observation from execution state.
        All reflection is native to Prometheus.
        """
        self.logger.info("Reflecting on execution...")
        return self._reflect(plan, result)

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _classify_intent(self, goal: str) -> Tuple[str, float]:
        """
        Score the goal against each intent category and return the
        best match with a confidence value in [0, 1].
        """
        goal_lower = goal.lower()
        scores: Dict[str, int] = {intent: 0 for intent in INTENT_KEYWORDS}

        for intent, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in goal_lower:
                    scores[intent] += 1

        best_intent = max(scores, key=lambda k: scores[k])
        best_score = scores[best_intent]

        if best_score == 0:
            return INTENT_GENERIC, 0.0

        max_possible = len(INTENT_KEYWORDS[best_intent])
        confidence = min(best_score / max_possible, 1.0)
        return best_intent, confidence

    # ------------------------------------------------------------------
    # Memory extraction
    # ------------------------------------------------------------------

    def _extract_memory_hints(self, memory: List[Dict]) -> List[str]:
        """Pull relevant content strings from recent memory entries."""
        hints = []
        for m in memory[:5]:
            content = m.get("content", "").strip()
            if content:
                hints.append(content[:300])
        return hints

    # ------------------------------------------------------------------
    # Task decomposition
    # ------------------------------------------------------------------

    def _decompose(
        self,
        goal: str,
        intent_type: str,
        context: Dict,
        memory_hints: List[str]
    ) -> List[Task]:
        """
        Build a dependency-aware task graph for the given intent.
        Each intent type has a canonical multi-step pattern.
        Memory hints can inject an additional context-loading task.
        """
        tasks: List[Task] = []

        # Optionally prepend a memory-context task
        if memory_hints:
            tasks.append(Task(
                id="task_0",
                description="Load relevant memory context into working state",
                tool_name="database_query",
                tool_args={"query": f"SELECT * FROM memory WHERE relevance > 0.7 LIMIT 5"},
                dependencies=[],
                expected_output="Memory context loaded"
            ))

        base_dep = ["task_0"] if memory_hints else []

        if intent_type == INTENT_CREATE:
            tasks += self._tasks_create(goal, base_dep)

        elif intent_type == INTENT_SEARCH:
            tasks += self._tasks_search(goal, base_dep)

        elif intent_type == INTENT_READ:
            tasks += self._tasks_read(goal, base_dep)

        elif intent_type == INTENT_WRITE:
            tasks += self._tasks_write(goal, base_dep)

        elif intent_type == INTENT_DELETE:
            tasks += self._tasks_delete(goal, base_dep)

        elif intent_type == INTENT_EXECUTE:
            tasks += self._tasks_execute(goal, base_dep)

        elif intent_type == INTENT_ANALYZE:
            tasks += self._tasks_analyze(goal, base_dep)

        elif intent_type == INTENT_NETWORK:
            tasks += self._tasks_network(goal, base_dep)

        elif intent_type == INTENT_DATABASE:
            tasks += self._tasks_database(goal, base_dep)

        else:
            tasks += self._tasks_generic(goal, base_dep)

        return tasks

    # ------------------------------------------------------------------
    # Per-intent task patterns
    # ------------------------------------------------------------------

    def _tasks_create(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Validate inputs and check preconditions",
                tool_name="code_execute",
                tool_args={"code": f"# Validate preconditions for: {goal}"},
                dependencies=base_dep,
                expected_output="Preconditions verified"
            ),
            Task(
                id="task_2",
                description="Scaffold or initialize the target artifact",
                tool_name="file_write",
                tool_args={"path": "", "content": ""},
                dependencies=["task_1"],
                expected_output="Artifact initialized"
            ),
            Task(
                id="task_3",
                description="Populate artifact with required content",
                tool_name="code_execute",
                tool_args={"code": f"# Populate artifact for: {goal}"},
                dependencies=["task_2"],
                expected_output="Artifact populated"
            ),
            Task(
                id="task_4",
                description="Validate artifact integrity and output",
                tool_name="code_execute",
                tool_args={"code": "# Validate output"},
                dependencies=["task_3"],
                expected_output="Artifact validated and ready"
            ),
        ]

    def _tasks_search(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Build search query from goal",
                tool_name="code_execute",
                tool_args={"code": f"query = '{goal}'"},
                dependencies=base_dep,
                expected_output="Query constructed"
            ),
            Task(
                id="task_2",
                description="Execute search against target source",
                tool_name="database_query",
                tool_args={"query": goal},
                dependencies=["task_1"],
                expected_output="Raw results returned"
            ),
            Task(
                id="task_3",
                description="Filter and rank results by relevance",
                tool_name="code_execute",
                tool_args={"code": "# Filter and rank results"},
                dependencies=["task_2"],
                expected_output="Ranked result set"
            ),
            Task(
                id="task_4",
                description="Format and surface final results",
                tool_name="code_execute",
                tool_args={"code": "# Format results for output"},
                dependencies=["task_3"],
                expected_output="Results formatted and ready"
            ),
        ]

    def _tasks_read(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Resolve target resource path or identifier",
                tool_name="code_execute",
                tool_args={"code": f"# Resolve path for: {goal}"},
                dependencies=base_dep,
                expected_output="Resource path resolved"
            ),
            Task(
                id="task_2",
                description="Read resource from storage or source",
                tool_name="file_read",
                tool_args={"path": ""},
                dependencies=["task_1"],
                expected_output="Resource contents loaded"
            ),
            Task(
                id="task_3",
                description="Parse and validate resource contents",
                tool_name="code_execute",
                tool_args={"code": "# Parse and validate contents"},
                dependencies=["task_2"],
                expected_output="Contents parsed and valid"
            ),
        ]

    def _tasks_write(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Load existing resource if present",
                tool_name="file_read",
                tool_args={"path": ""},
                dependencies=base_dep,
                expected_output="Existing resource loaded or confirmed absent"
            ),
            Task(
                id="task_2",
                description="Prepare updated content",
                tool_name="code_execute",
                tool_args={"code": f"# Prepare content for: {goal}"},
                dependencies=["task_1"],
                expected_output="Content prepared"
            ),
            Task(
                id="task_3",
                description="Write content to target",
                tool_name="file_write",
                tool_args={"path": "", "content": ""},
                dependencies=["task_2"],
                expected_output="Content written successfully"
            ),
            Task(
                id="task_4",
                description="Verify write succeeded",
                tool_name="file_read",
                tool_args={"path": ""},
                dependencies=["task_3"],
                expected_output="Write verified"
            ),
        ]

    def _tasks_delete(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Confirm target exists before deletion",
                tool_name="file_read",
                tool_args={"path": ""},
                dependencies=base_dep,
                expected_output="Target confirmed present"
            ),
            Task(
                id="task_2",
                description="Create backup or snapshot before deletion",
                tool_name="file_write",
                tool_args={"path": ".backup", "content": ""},
                dependencies=["task_1"],
                expected_output="Backup created"
            ),
            Task(
                id="task_3",
                description="Execute deletion",
                tool_name="os_command",
                tool_args={"command": ""},
                dependencies=["task_2"],
                expected_output="Target deleted"
            ),
            Task(
                id="task_4",
                description="Confirm deletion and clean up",
                tool_name="code_execute",
                tool_args={"code": "# Verify deletion"},
                dependencies=["task_3"],
                expected_output="Deletion confirmed"
            ),
        ]

    def _tasks_execute(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Validate execution environment and dependencies",
                tool_name="code_execute",
                tool_args={"code": "# Check environment"},
                dependencies=base_dep,
                expected_output="Environment validated"
            ),
            Task(
                id="task_2",
                description="Prepare execution parameters",
                tool_name="code_execute",
                tool_args={"code": f"# Prepare params for: {goal}"},
                dependencies=["task_1"],
                expected_output="Parameters prepared"
            ),
            Task(
                id="task_3",
                description="Execute target process or command",
                tool_name="os_command",
                tool_args={"command": ""},
                dependencies=["task_2"],
                expected_output="Process executed"
            ),
            Task(
                id="task_4",
                description="Capture and validate execution output",
                tool_name="code_execute",
                tool_args={"code": "# Validate output"},
                dependencies=["task_3"],
                expected_output="Output captured and valid"
            ),
        ]

    def _tasks_analyze(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Load data or artifact to be analyzed",
                tool_name="file_read",
                tool_args={"path": ""},
                dependencies=base_dep,
                expected_output="Data loaded"
            ),
            Task(
                id="task_2",
                description="Run structural inspection and surface metrics",
                tool_name="code_execute",
                tool_args={"code": f"# Inspect structure for: {goal}"},
                dependencies=["task_1"],
                expected_output="Structural metrics extracted"
            ),
            Task(
                id="task_3",
                description="Apply analytical logic and identify patterns",
                tool_name="code_execute",
                tool_args={"code": "# Pattern analysis"},
                dependencies=["task_2"],
                expected_output="Patterns identified"
            ),
            Task(
                id="task_4",
                description="Generate findings and recommendations",
                tool_name="code_execute",
                tool_args={"code": "# Compile findings"},
                dependencies=["task_3"],
                expected_output="Findings and recommendations produced"
            ),
        ]

    def _tasks_network(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Resolve endpoint and prepare request parameters",
                tool_name="code_execute",
                tool_args={"code": f"# Resolve endpoint for: {goal}"},
                dependencies=base_dep,
                expected_output="Endpoint and params ready"
            ),
            Task(
                id="task_2",
                description="Execute network request",
                tool_name="web_request",
                tool_args={"url": "", "method": "GET"},
                dependencies=["task_1"],
                expected_output="Response received"
            ),
            Task(
                id="task_3",
                description="Validate response status and parse payload",
                tool_name="code_execute",
                tool_args={"code": "# Parse and validate response"},
                dependencies=["task_2"],
                expected_output="Response validated and parsed"
            ),
            Task(
                id="task_4",
                description="Store or forward response data as required",
                tool_name="file_write",
                tool_args={"path": "", "content": ""},
                dependencies=["task_3"],
                expected_output="Response data stored"
            ),
        ]

    def _tasks_database(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description="Validate schema and connection before operation",
                tool_name="database_query",
                tool_args={"query": "SELECT 1"},
                dependencies=base_dep,
                expected_output="Connection and schema verified"
            ),
            Task(
                id="task_2",
                description="Build and validate target query or mutation",
                tool_name="code_execute",
                tool_args={"code": f"# Build query for: {goal}"},
                dependencies=["task_1"],
                expected_output="Query constructed and validated"
            ),
            Task(
                id="task_3",
                description="Execute database operation",
                tool_name="database_query",
                tool_args={"query": ""},
                dependencies=["task_2"],
                expected_output="Operation executed"
            ),
            Task(
                id="task_4",
                description="Verify result set and check for anomalies",
                tool_name="code_execute",
                tool_args={"code": "# Verify results"},
                dependencies=["task_3"],
                expected_output="Results verified"
            ),
        ]

    def _tasks_generic(self, goal: str, base_dep: List[str]) -> List[Task]:
        return [
            Task(
                id="task_1",
                description=f"Assess requirements for: {goal}",
                tool_name="code_execute",
                tool_args={"code": f"# Assess: {goal}"},
                dependencies=base_dep,
                expected_output="Requirements assessed"
            ),
            Task(
                id="task_2",
                description="Determine and prepare execution strategy",
                tool_name="code_execute",
                tool_args={"code": "# Prepare strategy"},
                dependencies=["task_1"],
                expected_output="Strategy prepared"
            ),
            Task(
                id="task_3",
                description="Execute primary action",
                tool_name="code_execute",
                tool_args={"code": f"# Execute: {goal}"},
                dependencies=["task_2"],
                expected_output="Action executed"
            ),
            Task(
                id="task_4",
                description="Validate outcome and confirm completion",
                tool_name="code_execute",
                tool_args={"code": "# Validate outcome"},
                dependencies=["task_3"],
                expected_output="Outcome validated"
            ),
        ]

    # ------------------------------------------------------------------
    # Reasoning narrative
    # ------------------------------------------------------------------

    def _build_reasoning(
        self,
        goal: str,
        intent_type: str,
        confidence: float,
        memory_hints: List[str]
    ) -> str:
        lines = [
            f"Goal: {goal}",
            f"Classified intent: {intent_type} (confidence={confidence:.2f})",
        ]
        if memory_hints:
            lines.append(f"Memory context: {len(memory_hints)} relevant hint(s) incorporated")
        else:
            lines.append("Memory context: none available")
        lines.append(
            f"Decomposition: native Prometheus task graph — "
            f"{'4 tasks + memory preload' if memory_hints else '4 tasks'}"
        )
        return " | ".join(lines)

    # ------------------------------------------------------------------
    # Reflection
    # ------------------------------------------------------------------

    def _reflect(self, plan: Plan, result: ExecutionResult) -> Observation:
        completed = len(result.tasks_completed)
        failed = len(result.tasks_failed)
        total = completed + failed

        full_success = failed == 0 and result.is_complete
        full_failure = completed == 0 and failed > 0
        partial = not full_success and not full_failure

        # --- Full success ---
        if full_success:
            return Observation(
                summary=(
                    f"All {completed} task(s) completed successfully for goal: '{plan.goal}'"
                ),
                success=True,
                lessons_learned=(
                    "Execution nominal across all tasks. "
                    "Plan decomposition and tool selection were appropriate."
                ),
                next_steps=None,
                should_continue=False
            )

        # --- Full failure ---
        if full_failure:
            error_detail = result.error or "unknown error"
            failed_ids = ", ".join(result.tasks_failed)
            return Observation(
                summary=(
                    f"Complete failure — 0/{total} tasks completed. "
                    f"Failed tasks: [{failed_ids}]. Error: {error_detail}"
                ),
                success=False,
                lessons_learned=(
                    f"No tasks succeeded. Root cause: {error_detail}. "
                    "Review tool availability, input validity, and permission boundaries "
                    "before retrying."
                ),
                next_steps=(
                    "Inspect failed task inputs and tool configs. "
                    "Verify orchestration layer connectivity. Re-plan if necessary."
                ),
                should_continue=True
            )

        # --- Partial success ---
        completed_ids = ", ".join(result.tasks_completed)
        failed_ids = ", ".join(result.tasks_failed)
        error_detail = result.error or "see failed task logs"

        # Determine if enough progress was made to be useful
        progress_ratio = completed / total if total > 0 else 0
        usable = progress_ratio >= 0.5

        return Observation(
            summary=(
                f"Partial execution — {completed}/{total} task(s) completed. "
                f"Completed: [{completed_ids}]. Failed: [{failed_ids}]."
            ),
            success=False,
            lessons_learned=(
                f"Progress ratio: {progress_ratio:.0%}. "
                f"{'Partial results may be usable.' if usable else 'Insufficient progress — replan recommended.'} "
                f"Failure detail: {error_detail}."
            ),
            next_steps=(
                f"Retry failed tasks [{failed_ids}] with adjusted parameters. "
                f"{'Build on completed task outputs.' if usable else 'Consider full replan from task_1.'}"
            ),
            should_continue=True
        )
