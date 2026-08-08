"""
Autonomous ad campaign runner.

Pulls Shopify (if keys) → research → plan → package on disk → optional Meta PAUSED launch.
Never asks the user follow-up questions; all knobs from config + env.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from growth.ads.meta_client import MetaAdsClient
from growth.ads.planner import CampaignPlanner
from growth.ads.shopify_client import ShopifyClient

try:
    from utils.config import cfg

    ROOT = cfg.ROOT
except Exception:
    ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CONFIG = ROOT / "config" / "shopify_ads.yaml"


class AdCampaignOrchestrator:
    def __init__(self, config_path: Optional[str | Path] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG
        self.config = self._load_config()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            with open(self.config_path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def run(
        self,
        *,
        mode: Optional[str] = None,
        research: bool = True,
        user_msg: str = "",
    ) -> Dict[str, Any]:
        cfg = self.config
        brand = cfg.get("brand") or {}
        budget = cfg.get("budget") or {}
        autonomy = cfg.get("autonomy") or {}
        catalog_cfg = cfg.get("catalog") or {}

        mode = (mode or autonomy.get("mode") or "dry_run").lower()
        if mode == "package":
            mode = "dry_run"
        # launch only if explicitly allowed
        launch_env = os.getenv("ADS_AUTONOMOUS_LAUNCH", "").lower() in ("1", "true", "yes")
        if mode == "launch" and not launch_env:
            mode = "dry_run"
            launch_blocked = "ADS_AUTONOMOUS_LAUNCH not set — package only"
        else:
            launch_blocked = None

        # 1) products
        shopify = ShopifyClient()
        products: List[dict] = []
        catalog_source = "fallback"
        max_p = int(catalog_cfg.get("max_products", 8))
        if shopify.configured:
            try:
                products = shopify.fetch_catalog(max_products=max_p)
                catalog_source = "shopify"
            except Exception as e:
                catalog_source = f"shopify_error:{e}"
                products = []

        # 2) research
        research_hits: List[dict] = []
        if research and autonomy.get("research", True):
            research_hits = self._research(brand)

        # 3) store url
        store_url = brand.get("website") or ""
        if not store_url and shopify.store:
            store_url = f"https://{shopify.store}"

        # 4) plan
        planner = CampaignPlanner(brand, budget, autonomy)
        plan = planner.plan(
            products,
            research=research_hits,
            store_url=store_url,
            mode=mode,
        )
        plan_dict = plan.to_dict()

        # 5) write package
        out_dir = ROOT / (cfg.get("output_dir") or "data/growth/campaigns")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        run_dir = out_dir / f"run_{stamp}"
        run_dir.mkdir(parents=True, exist_ok=True)
        plan_path = run_dir / "campaign_plan.json"
        plan_path.write_text(json.dumps(plan_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        brief_path = run_dir / "BRIEF.md"
        brief_path.write_text(self._brief_md(plan_dict, catalog_source), encoding="utf-8")
        meta_export = run_dir / "meta_launch_payload.json"
        meta_export.write_text(
            json.dumps({"campaigns": plan_dict.get("campaigns"), "status": "PAUSED"}, indent=2),
            encoding="utf-8",
        )

        launch_result = None
        if mode == "launch":
            meta = MetaAdsClient()
            if meta.configured:
                try:
                    launch_result = meta.launch_from_plan(plan_dict, status="PAUSED")
                    (run_dir / "meta_launch_result.json").write_text(
                        json.dumps(launch_result, indent=2), encoding="utf-8"
                    )
                except Exception as e:
                    launch_result = {"errors": [str(e)]}
            else:
                launch_result = {"errors": ["Meta credentials incomplete"]}

        result = {
            "status": "ok",
            "mode": mode,
            "catalog_source": catalog_source,
            "products": len(plan_dict.get("products") or []),
            "campaigns": len(plan_dict.get("campaigns") or []),
            "creatives": len(plan_dict.get("creative_matrix") or []),
            "research_hits": len(research_hits),
            "output_dir": str(run_dir),
            "plan_path": str(plan_path),
            "brief_path": str(brief_path),
            "launch": launch_result,
            "launch_blocked": launch_blocked,
            "shopify_configured": shopify.configured,
            "meta_configured": MetaAdsClient().configured,
            "user_msg": user_msg[:200],
            "plan_summary": {
                "brand": plan_dict.get("brand"),
                "niche": plan_dict.get("niche"),
                "campaign_names": [c.get("name") for c in plan_dict.get("campaigns") or []],
                "daily_test_usd": budget.get("test_daily_usd"),
                "checklist": plan_dict.get("checklist"),
            },
        }
        result["formatted"] = self.format_for_chat(result)
        return result

    def _research(self, brand: dict) -> List[dict]:
        niche = brand.get("niche") or "ecommerce"
        queries = [
            f"Shopify Meta ads best practices {niche} 2025 2026",
            f"Facebook ads ecommerce creative hooks {niche}",
        ]
        hits: List[dict] = []
        try:
            from tools.web_search import search_web

            for q in queries:
                res = search_web(q, num_results=4)
                for r in res.get("results") or []:
                    hits.append(r)
        except Exception:
            pass
        return hits

    def _brief_md(self, plan: dict, catalog_source: str) -> str:
        lines = [
            f"# Ad campaign brief — {plan.get('brand')}",
            "",
            f"- Niche: {plan.get('niche')}",
            f"- Generated: {plan.get('generated_at')}",
            f"- Catalog: {catalog_source}",
            f"- Mode: {plan.get('mode')}",
            "",
            "## Research notes",
        ]
        for n in plan.get("research_notes") or []:
            lines.append(f"- {n}")
        lines += ["", "## Campaigns"]
        for c in plan.get("campaigns") or []:
            lines.append(f"### {c.get('name')}")
            lines.append(f"- Objective: {c.get('objective')} | daily ${c.get('daily_budget_usd')}")
            for a in c.get("adsets") or []:
                lines.append(f"  - Ad set: {a.get('name')} (${a.get('daily_budget_usd')}/day, {len(a.get('ads') or [])} ads)")
        lines += ["", "## Creatives (sample)"]
        for cr in (plan.get("creative_matrix") or [])[:6]:
            lines.append(f"- **{cr.get('product_title')}** [{cr.get('angle')}]")
            lines.append(f"  - {cr.get('primary_text')}")
            lines.append(f"  - Headline: {cr.get('headline')}")
        lines += ["", "## Checklist"]
        for item in plan.get("checklist") or []:
            lines.append(f"- [ ] {item}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def format_for_chat(result: Dict[str, Any]) -> str:
        if result.get("status") != "ok":
            return result.get("error") or "Ad campaign failed."

        lines = [
            "🟠 Shopify ad campaign — built (no extra questions)",
            "",
            f"Mode: {result.get('mode')}",
            f"Catalog: {result.get('catalog_source')} ({result.get('products')} products)",
            f"Campaigns: {result.get('campaigns')} | Creatives: {result.get('creatives')}",
            f"Research hits: {result.get('research_hits')}",
            f"Shopify API: {'yes' if result.get('shopify_configured') else 'no (used config/fallback)'}",
            f"Meta API: {'yes' if result.get('meta_configured') else 'no'}",
            "",
        ]
        summary = result.get("plan_summary") or {}
        if summary.get("campaign_names"):
            lines.append("Campaigns:")
            for name in summary["campaign_names"]:
                lines.append(f"  • {name}")
            lines.append("")
        lines.append(f"Package: {result.get('output_dir')}")
        lines.append(f"Brief: {result.get('brief_path')}")

        if result.get("launch_blocked"):
            lines.append(f"\nLaunch: skipped — {result['launch_blocked']}")
        elif result.get("launch"):
            launch = result["launch"]
            if launch.get("errors"):
                lines.append(f"\nMeta launch errors: {'; '.join(launch['errors'])[:300]}")
            else:
                lines.append(
                    f"\nMeta: created {launch.get('ads_created', 0)} ads as {launch.get('status', 'PAUSED')} "
                    f"({len(launch.get('campaigns') or [])} campaigns). Flip ACTIVE in Ads Manager to spend."
                )
        else:
            lines.append(
                "\nTo push PAUSED structure to Meta: set META_* keys + ADS_AUTONOMOUS_LAUNCH=1 "
                "and mode=launch in config/shopify_ads.yaml (or /ads launch)."
            )

        lines.append("\nEdit defaults anytime in config/shopify_ads.yaml + .env — then /ads again.")
        return "\n".join(lines)
