import re

def interpret_command(user_input: str) -> dict:
    """Analyze user text input and map it to a structured plan with clear intent and steps."""
    text = user_input.strip().lower()

    # --- Recognize patterns ---
    if text.startswith("create skill"):
        skill_name = re.sub(r"^create skill\s+", "", text).strip().replace(" ", "_")
        return {
            "intent": "create_skill",
            "steps": [{"action": f"create_skill", "description": f"Create new skill '{skill_name}'", "skill_name": skill_name}]
        }

    if text.startswith("run") or text.startswith("execute"):
        skill_name = re.sub(r"^(run|execute)\s+", "", text).strip().replace(" ", "_")
        return {
            "intent": "run_skill",
            "steps": [{"action": f"run_skill", "description": f"Run skill '{skill_name}'", "skill_name": skill_name}]
        }

    # fallback: general reasoning
    return {
        "intent": "unknown",
        "steps": [
            {"action": "reflect", "description": "Reflect on unknown command"},
            {"action": "respond", "description": "Provide general response"},
        ],
    }
