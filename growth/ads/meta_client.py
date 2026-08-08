"""Meta Marketing API — create campaigns PAUSED by default."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class MetaAdsClient:
    def __init__(
        self,
        access_token: Optional[str] = None,
        ad_account_id: Optional[str] = None,
        page_id: Optional[str] = None,
        pixel_id: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.token = access_token or os.getenv("META_ACCESS_TOKEN", "")
        acct = ad_account_id or os.getenv("META_AD_ACCOUNT_ID", "")
        if acct and not str(acct).startswith("act_"):
            acct = f"act_{acct}"
        self.ad_account_id = acct
        self.page_id = page_id or os.getenv("META_PAGE_ID", "")
        self.pixel_id = pixel_id or os.getenv("META_PIXEL_ID", "")
        ver = (api_version or os.getenv("META_API_VERSION", "v21.0")).lstrip("v")
        self.api_version = f"v{ver}"

    @property
    def configured(self) -> bool:
        return bool(self.token and self.ad_account_id and self.page_id)

    def _graph(self, path: str, method: str = "GET", params: Optional[dict] = None) -> dict:
        if not self.token:
            raise RuntimeError("META_ACCESS_TOKEN not set")
        base = f"https://graph.facebook.com/{self.api_version}/{path.lstrip('/')}"
        params = dict(params or {})
        params["access_token"] = self.token
        data = None
        url = base
        if method == "GET":
            url = f"{base}?{urllib.parse.urlencode(params)}"
        else:
            data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Meta API {e.code}: {err[:800]}") from e

    def create_campaign(self, name: str, *, objective: str = "OUTCOME_SALES", status: str = "PAUSED") -> dict:
        return self._graph(
            f"{self.ad_account_id}/campaigns",
            method="POST",
            params={
                "name": name,
                "objective": objective,
                "status": status,
                "special_ad_categories": json.dumps([]),
            },
        )

    def create_adset(
        self,
        name: str,
        campaign_id: str,
        *,
        daily_budget_cents: int,
        countries: List[str],
        optimization_goal: str = "OFFSITE_CONVERSIONS",
        status: str = "PAUSED",
    ) -> dict:
        targeting = {"geo_locations": {"countries": countries}, "age_min": 18, "age_max": 65}
        params: Dict[str, Any] = {
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": str(daily_budget_cents),
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization_goal,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": json.dumps(targeting),
            "status": status,
        }
        if self.pixel_id and optimization_goal == "OFFSITE_CONVERSIONS":
            params["promoted_object"] = json.dumps(
                {"pixel_id": self.pixel_id, "custom_event_type": "PURCHASE"}
            )
        return self._graph(f"{self.ad_account_id}/adsets", method="POST", params=params)

    def create_adcreative_link(
        self,
        name: str,
        *,
        message: str,
        link: str,
        headline: str,
        description: str = "",
        image_url: Optional[str] = None,
        call_to_action: str = "SHOP_NOW",
    ) -> dict:
        link_data: Dict[str, Any] = {
            "message": message,
            "link": link,
            "name": headline,
            "description": description,
            "call_to_action": {"type": call_to_action},
        }
        if image_url:
            link_data["picture"] = image_url
        return self._graph(
            f"{self.ad_account_id}/adcreatives",
            method="POST",
            params={
                "name": name,
                "object_story_spec": json.dumps({"page_id": self.page_id, "link_data": link_data}),
            },
        )

    def create_ad(self, name: str, adset_id: str, creative_id: str, *, status: str = "PAUSED") -> dict:
        return self._graph(
            f"{self.ad_account_id}/ads",
            method="POST",
            params={
                "name": name,
                "adset_id": adset_id,
                "creative": json.dumps({"creative_id": creative_id}),
                "status": status,
            },
        )

    def launch_from_plan(self, plan: dict, *, status: str = "PAUSED", max_ads: int = 8) -> Dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Meta not configured (META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_PAGE_ID)")
        results: Dict[str, Any] = {"campaigns": [], "errors": [], "ads_created": 0, "status": status}
        ads_created = 0
        for camp in plan.get("campaigns") or []:
            try:
                c_resp = self.create_campaign(
                    camp.get("name", "Prometheous Campaign"),
                    objective=camp.get("objective", "OUTCOME_SALES"),
                    status=status,
                )
                campaign_id = c_resp.get("id")
                camp_out: Dict[str, Any] = {"id": campaign_id, "name": camp.get("name"), "adsets": []}
                countries = camp.get("countries") or ["US"]
                for adset in camp.get("adsets") or []:
                    daily_cents = int(float(adset.get("daily_budget_usd", 10)) * 100)
                    a_resp = self.create_adset(
                        adset.get("name", "AdSet"),
                        campaign_id,
                        daily_budget_cents=daily_cents,
                        countries=adset.get("countries") or countries,
                        optimization_goal=adset.get("optimization_goal", "OFFSITE_CONVERSIONS"),
                        status=status,
                    )
                    adset_id = a_resp.get("id")
                    adset_out: Dict[str, Any] = {"id": adset_id, "name": adset.get("name"), "ads": []}
                    for ad in adset.get("ads") or []:
                        if ads_created >= max_ads:
                            break
                        cr = self.create_adcreative_link(
                            ad.get("name", "Creative"),
                            message=ad.get("primary_text", ""),
                            link=ad.get("link", ""),
                            headline=ad.get("headline", ""),
                            description=ad.get("description", ""),
                            image_url=ad.get("image_url") or None,
                            call_to_action=ad.get("cta", "SHOP_NOW"),
                        )
                        ad_resp = self.create_ad(ad.get("name", "Ad"), adset_id, cr.get("id"), status=status)
                        adset_out["ads"].append({"id": ad_resp.get("id"), "creative_id": cr.get("id")})
                        ads_created += 1
                    camp_out["adsets"].append(adset_out)
                results["campaigns"].append(camp_out)
            except Exception as e:
                results["errors"].append(str(e))
        results["ads_created"] = ads_created
        return results
