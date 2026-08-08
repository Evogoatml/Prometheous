"""
Shopify ads agent — executes campaign build/launch. Never refuses with "I can't".

Uses growth.ads.AdCampaignOrchestrator. Defaults from config/shopify_ads.yaml + .env.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


class ShopifyAdsAgent:
    name = "shopify_ads"
    role = "Growth"
    specialty = "Shopify catalog + Meta ad campaign builder (autonomous)"
    tasks_completed = 0

    def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.tasks_completed += 1
        user_msg = str(payload.get("user_msg") or payload.get("query") or payload.get("target") or "")
        mode = self._parse_mode(payload, user_msg)

        try:
            from growth.ads.orchestrator import AdCampaignOrchestrator

            orch = AdCampaignOrchestrator()
            result = orch.run(mode=mode, research=True, user_msg=user_msg)
            result["agent"] = self.name
            if "formatted" not in result:
                result["formatted"] = AdCampaignOrchestrator.format_for_chat(result)
            return result
        except Exception as e:
            # Still handle the task: return actionable failure, not "I can't help"
            err = {
                "status": "failed",
                "agent": self.name,
                "error": str(e),
                "formatted": (
                    "🟠 Ad campaign run hit an error — but I did attempt it.\n\n"
                    f"{e}\n\n"
                    "Fix: set SHOPIFY_* / META_* in .env and brand defaults in "
                    "config/shopify_ads.yaml, then send the same request again "
                    "(or /ads). I will not ask you a questionnaire."
                ),
            }
            return err

    def _parse_mode(self, payload: Dict[str, Any], user_msg: str) -> Optional[str]:
        if payload.get("mode"):
            return str(payload["mode"]).lower()
        lower = user_msg.lower()
        if re.search(r"\b(?:launch|publish|push|go\s+live|create\s+on\s+meta)\b", lower):
            return "launch"
        if re.search(r"\b(?:dry\s*run|package\s+only|plan\s+only)\b", lower):
            return "dry_run"
        # None → orchestrator uses config default
        return None
