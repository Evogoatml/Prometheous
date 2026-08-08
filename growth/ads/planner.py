"""Rule-based campaign plan — no user Q&A; uses config brand/budget."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


BEST_PRACTICES = [
    "Hero single-product tests before catalog ads.",
    "3–5 creative hooks per product; kill low CTR after day 3.",
    "UGC-style hooks beat polished film for cold traffic.",
    "Match ad promise to landing page.",
    "Create structure PAUSED; flip ACTIVE in Ads Manager when ready.",
    "Retarget after pixel has history (50+ events).",
]

ANGLE_TEMPLATES = [
    ("pain", "Stop settling for less. {product} delivers {usp}."),
    ("social_proof", "Shoppers in {niche} are switching to {product}."),
    ("offer", "{product} — {price}. {usp}"),
    ("curiosity", "Why {product} is trending in {niche} right now."),
    ("ugc", "Honest review energy: {product} actually helps."),
]


@dataclass
class CampaignPlan:
    brand: str
    niche: str
    generated_at: str
    research_notes: List[str]
    products: List[dict]
    campaigns: List[dict]
    audiences: List[dict]
    creative_matrix: List[dict]
    checklist: List[str]
    mode: str = "dry_run"

    def to_dict(self) -> dict:
        return asdict(self)


class CampaignPlanner:
    def __init__(self, brand_cfg: dict, budget_cfg: dict, autonomy_cfg: dict):
        self.brand = brand_cfg
        self.budget = budget_cfg
        self.autonomy = autonomy_cfg

    def plan(
        self,
        products: List[dict],
        *,
        research: Optional[List[dict]] = None,
        store_url: str = "",
        mode: str = "dry_run",
    ) -> CampaignPlan:
        research_notes = []
        for r in (research or [])[:8]:
            title = r.get("title") or ""
            snip = r.get("snippet") or ""
            if title or snip:
                research_notes.append(f"{title}: {snip}"[:240])
        if not research_notes:
            research_notes.append("Built-in ecommerce benchmarks (no live search hits).")
        research_notes.extend(BEST_PRACTICES[:3])

        if not products:
            products = [self._fallback_product()]
        products = products[: int(self.autonomy.get("max_products", 8) or 8)]

        creatives = []
        for p in products:
            creatives.extend(self._creatives(p))

        campaigns = self._campaigns(products, creatives, store_url)
        return CampaignPlan(
            brand=self.brand.get("name", "Store"),
            niche=self.brand.get("niche", "ecommerce"),
            generated_at=datetime.now(timezone.utc).isoformat(),
            research_notes=research_notes,
            products=products,
            campaigns=campaigns,
            audiences=self._audiences(),
            creative_matrix=creatives,
            checklist=[
                "Pixel Purchase event on thank-you page",
                "Creative matches product page",
                f"Test budget ${self.budget.get('test_daily_usd', 10)}/day",
                "Start PAUSED → review → ACTIVE",
                "Kill losers day 3; scale winners",
            ],
            mode=mode,
        )

    def _fallback_product(self) -> dict:
        return {
            "id": "sample-1",
            "title": f"{self.brand.get('name', 'Store')} Hero Product",
            "handle": "hero-product",
            "body_html": self.brand.get("usp", ""),
            "product_type": self.brand.get("niche", ""),
            "tags": ["bestsellers"],
            "price": "49.00",
            "image_url": "",
            "url_path": "/products/hero-product",
        }

    def _creatives(self, product: dict) -> List[dict]:
        title = product.get("title", "Product")
        price = product.get("price", "")
        usp = self.brand.get("usp", "Quality you can trust")
        niche = self.brand.get("niche", "ecommerce")
        n = int(self.autonomy.get("angles_per_product", 3) or 3)
        out = []
        for angle, tmpl in ANGLE_TEMPLATES[:n]:
            primary = tmpl.format(
                product=title,
                price=f"${price}" if price else "great price",
                usp=usp,
                niche=niche,
            )
            hooks = [
                f"Wait — {title}?",
                f"I switched to {title}",
                f"{title}: {niche} upgrade",
            ]
            out.append(
                {
                    "product_id": product.get("id"),
                    "product_title": title,
                    "angle": angle,
                    "primary_text": primary,
                    "headline": title[:40],
                    "description": usp[:30],
                    "cta": "SHOP_NOW",
                    "ugc_script": (
                        f"[HOOK] {hooks[0]}\n[DEMO] Show {title}\n"
                        f"[PROOF] ${price} — {usp}\n[CTA] Shop Now"
                    ),
                    "hooks": hooks,
                    "image_url": product.get("image_url") or "",
                    "price": price,
                }
            )
        return out

    def _audiences(self) -> List[dict]:
        geos = self.brand.get("target_geo") or ["US"]
        niche = self.brand.get("niche", "shopping")
        return [
            {"name": "Cold Broad", "type": "cold", "geo": geos},
            {"name": f"Interest — {niche}", "type": "interest", "geo": geos},
            {"name": "Retarget VC 7d", "type": "retarget", "geo": geos},
        ]

    def _link(self, product: dict, store_url: str) -> str:
        base = (store_url or self.brand.get("website") or "").rstrip("/")
        path = product.get("url_path") or f"/products/{product.get('handle', '')}"
        return f"{base}{path}" if base else path

    def _campaigns(self, products: List[dict], creatives: List[dict], store_url: str) -> List[dict]:
        test_budget = float(self.budget.get("test_daily_usd", 10))
        daily_cap = float(self.budget.get("daily_usd", 25))
        max_adsets = int(self.autonomy.get("max_adsets_per_campaign", 3))
        max_ads = int(self.autonomy.get("max_ads_per_adset", 4))
        geos = self.brand.get("target_geo") or ["US"]
        brand = self.brand.get("name", "Store")
        day = datetime.now(timezone.utc).strftime("%Y%m%d")

        heroes = products[: min(3, len(products))]
        per = max(5.0, min(test_budget, daily_cap) / max(len(heroes), 1))
        adsets = []
        for p in heroes[:max_adsets]:
            ads = []
            for i, c in enumerate([x for x in creatives if x.get("product_id") == p.get("id")][:max_ads]):
                ads.append(
                    {
                        "name": f"{brand[:12]}|{p.get('title', '')[:18]}|{c.get('angle')}|{i+1}",
                        "primary_text": c.get("primary_text", ""),
                        "headline": c.get("headline", "")[:40],
                        "description": c.get("description", ""),
                        "cta": "SHOP_NOW",
                        "link": self._link(p, store_url),
                        "image_url": c.get("image_url") or p.get("image_url") or "",
                        "ugc_script": c.get("ugc_script", ""),
                        "angle": c.get("angle"),
                    }
                )
            adsets.append(
                {
                    "name": f"Test|{p.get('title', 'p')[:28]}|Broad",
                    "daily_budget_usd": round(per, 2),
                    "countries": geos,
                    "optimization_goal": "OFFSITE_CONVERSIONS",
                    "ads": ads,
                }
            )

        campaigns = [
            {
                "name": f"{brand} | Test | {day}",
                "objective": "OUTCOME_SALES",
                "daily_budget_usd": min(test_budget, daily_cap),
                "countries": geos,
                "phase": "testing",
                "adsets": adsets,
            }
        ]
        if int(self.autonomy.get("max_campaigns", 2)) >= 2 and products:
            p0 = products[0]
            campaigns.append(
                {
                    "name": f"{brand} | Retarget | {day}",
                    "objective": "OUTCOME_SALES",
                    "daily_budget_usd": max(5.0, min(10.0, daily_cap * 0.3)),
                    "countries": geos,
                    "phase": "retarget",
                    "adsets": [
                        {
                            "name": "RT|VC7",
                            "daily_budget_usd": max(5.0, min(10.0, daily_cap * 0.3)),
                            "countries": geos,
                            "optimization_goal": "OFFSITE_CONVERSIONS",
                            "ads": [
                                {
                                    "name": f"{brand}|RT",
                                    "primary_text": f"Still thinking about {p0.get('title')}? {self.brand.get('usp', '')}",
                                    "headline": (p0.get("title") or "Your cart")[:40],
                                    "description": "Complete your order",
                                    "cta": "SHOP_NOW",
                                    "link": self._link(p0, store_url),
                                    "image_url": p0.get("image_url") or "",
                                }
                            ],
                        }
                    ],
                }
            )
        return campaigns
