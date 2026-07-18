"""Shopify Admin API — product catalog."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional


class ShopifyClient:
    def __init__(
        self,
        store: Optional[str] = None,
        token: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        self.store = (
            (store or os.getenv("SHOPIFY_STORE", ""))
            .replace("https://", "")
            .replace("http://", "")
            .strip("/")
        )
        self.token = token or os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        self.api_version = api_version or os.getenv("SHOPIFY_API_VERSION", "2024-10")

    @property
    def configured(self) -> bool:
        return bool(self.store and self.token)

    def _request(self, path: str) -> dict:
        if not self.configured:
            raise RuntimeError("Shopify not configured (SHOPIFY_STORE + SHOPIFY_ACCESS_TOKEN)")
        url = f"https://{self.store}/admin/api/{self.api_version}/{path.lstrip('/')}"
        req = urllib.request.Request(
            url,
            headers={
                "X-Shopify-Access-Token": self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Shopify API {e.code}: {err[:500]}") from e

    def list_products(self, limit: int = 50, status: str = "active") -> List[Dict[str, Any]]:
        qs = urllib.parse.urlencode({"limit": min(limit, 250), "status": status})
        return list((self._request(f"products.json?{qs}")).get("products") or [])

    def normalize_products(self, raw: List[dict], max_products: int = 8) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for p in raw[:max_products]:
            images = p.get("images") or []
            variants = p.get("variants") or []
            price = variants[0].get("price") if variants else "0"
            out.append(
                {
                    "id": str(p.get("id", "")),
                    "title": p.get("title") or "Untitled",
                    "handle": p.get("handle") or "",
                    "body_html": (p.get("body_html") or "")[:800],
                    "product_type": p.get("product_type") or "",
                    "tags": [t.strip() for t in (p.get("tags") or "").split(",") if t.strip()],
                    "price": str(price),
                    "compare_at_price": str(variants[0].get("compare_at_price") or "") if variants else "",
                    "image_url": (images[0].get("src") if images else "") or "",
                    "url_path": f"/products/{p.get('handle', '')}",
                }
            )
        return out

    def fetch_catalog(self, max_products: int = 8) -> List[Dict[str, Any]]:
        return self.normalize_products(self.list_products(limit=max_products), max_products)
