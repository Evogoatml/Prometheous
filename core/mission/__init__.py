"""
Mission pipeline — plan → code → deploy → execute.

Given a task, Prometheous:
  1. Plans what must be done (steps, agents, artifacts)
  2. Writes code (scripts + agent modules) when needed
  3. Deploys those agents onto the orchestrator
  4. Runs the plan until the work product exists
"""
from core.mission.conductor import MissionConductor, MissionResult, get_conductor
from core.mission.fleet import build_fleet, max_agents

__all__ = [
    "MissionConductor",
    "MissionResult",
    "get_conductor",
    "build_fleet",
    "max_agents",
]
