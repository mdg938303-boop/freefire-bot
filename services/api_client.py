"""
একাধিক ধরনের diamond top-up provider API সাপোর্ট করার জন্য এই ফাইলে দুটো ক্লায়েন্ট
আছে, দুটোরই একই রকম মেথড নাম (add_order/get_status/get_balance) — যাতে
services/orders.py ও services/order_sync.py কোনো provider type না জেনেই একই
কোডে কাজ করতে পারে ("duck typing").

  - EpinbyClient    -> epinby.com-এর মতো আধুনিক REST JSON API (X-API-KEY header)
  - SmmGenericClient -> পুরনো-ধাঁচের SMM panel style form-data API
    (action=add/status/balance) — অনেক BD reseller panel এই ফরম্যাট ব্যবহার করে

get_provider_client(provider) factory function দিয়ে Provider.provider_type
অনুযায়ী সঠিক ক্লায়েন্ট তৈরি হয়।
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class ApiClientError(Exception):
    pass


# Normalized status values every client's get_status() must map into.
STATUS_COMPLETED = "completed"
STATUS_PROCESSING = "processing"
STATUS_FAILED = "failed"


def _normalize_status(raw: str) -> str:
    raw = (raw or "").strip().lower()
    if raw in {"completed", "complete", "success", "delivered", "done"}:
        return STATUS_COMPLETED
    if raw in {"canceled", "cancelled", "failed", "refunded", "error", "rejected", "partial_refund"}:
        return STATUS_FAILED
    return STATUS_PROCESSING  # pending, processing, in_progress, awaiting, ইত্যাদি


# ----------------------------------------------------------------------
# EPINBY — REST JSON API, header-based auth (https://epinby.com/docs)
# ----------------------------------------------------------------------
class EpinbyClient:
    def __init__(self, base_url: str, api_key: str, api_secret: str | None = None, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self.api_key, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, json_body: dict | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self._headers()) as http:
                async with http.request(method, url, json=json_body) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception as exc:  # noqa: BLE001
                        text = await resp.text()
                        raise ApiClientError(f"Invalid JSON response: {text[:200]}") from exc
                    if resp.status >= 400 or data.get("success") is False:
                        err = data.get("error", {})
                        message = err.get("message") if isinstance(err, dict) else str(err) or f"HTTP {resp.status}"
                        raise ApiClientError(message)
                    return data
        except aiohttp.ClientError as exc:
            raise ApiClientError(str(exc)) from exc

    async def get_balance(self) -> dict[str, Any]:
        result = await self._request("GET", "/getMe")
        return result.get("data", result)

    async def validate_player(self, product_id: str, player_id: str, server_id: str | None = None) -> dict[str, Any]:
        """ঐচ্ছিক: অর্ডারের আগে Player ID যাচাই করে nickname ফেরত দেয় (Epinby-বিশেষ ফিচার)।"""
        body: dict[str, Any] = {"product_id": product_id, "player_id": player_id}
        if server_id:
            body["server_id"] = server_id
        result = await self._request("POST", "/validate-player", body)
        return result.get("data", result)

    async def add_order(self, product_id: str, player_id: str, quantity: int = 1) -> str:
        body = {"product_id": product_id, "qty": quantity, "player_id": player_id}
        result = await self._request("POST", "/order", body)
        data = result.get("data", result)
        order_id = data.get("order_id") or data.get("id")
        if not order_id:
            raise ApiClientError(f"Unexpected order response: {result}")
        return str(order_id)

    async def get_status(self, order_id: str) -> dict[str, Any]:
        result = await self._request("GET", f"/order/{order_id}")
        data = result.get("data", result)
        raw_status = str(data.get("status", ""))
        return {"status": _normalize_status(raw_status), "raw": raw_status}


# ----------------------------------------------------------------------
# GENERIC SMM PANEL — form-data, action=add/status/balance
# ----------------------------------------------------------------------
class SmmGenericClient:
    def __init__(self, base_url: str, api_key: str, api_secret: str | None = None, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = {"key": self.api_key, **payload}
        if self.api_secret:
            data["secret"] = self.api_secret
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as http:
                async with http.post(self.base_url, data=data) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        logger.warning("Provider API HTTP %s: %s", resp.status, text[:300])
                        raise ApiClientError(f"HTTP {resp.status}")
                    try:
                        return await resp.json(content_type=None)
                    except Exception as exc:  # noqa: BLE001
                        raise ApiClientError(f"Invalid JSON response: {text[:200]}") from exc
        except aiohttp.ClientError as exc:
            raise ApiClientError(str(exc)) from exc

    async def get_balance(self) -> dict[str, Any]:
        result = await self._post({"action": "balance"})
        if "error" in result:
            raise ApiClientError(str(result["error"]))
        return result

    async def add_order(self, service_id: str, player_id: str, quantity: int = 1) -> str:
        result = await self._post({"action": "add", "service": service_id, "link": player_id, "quantity": quantity})
        if "error" in result:
            raise ApiClientError(str(result["error"]))
        if "order" not in result:
            raise ApiClientError(f"Unexpected response: {result}")
        return str(result["order"])

    async def get_status(self, order_id: str) -> dict[str, Any]:
        result = await self._post({"action": "status", "order": order_id})
        if "error" in result:
            raise ApiClientError(str(result["error"]))
        raw_status = str(result.get("status", ""))
        return {"status": _normalize_status(raw_status), "raw": raw_status}


PROVIDER_TYPES = {
    "EPINBY": "Epinby (epinby.com)",
    "SMM_GENERIC": "Generic SMM Panel (action=add/status)",
}


def get_provider_client(provider) -> EpinbyClient | SmmGenericClient:
    """provider: database.models.ApiProvider ইনস্ট্যান্স"""
    if provider.provider_type == "EPINBY":
        return EpinbyClient(provider.base_url, provider.api_key, provider.api_secret)
    return SmmGenericClient(provider.base_url, provider.api_key, provider.api_secret)
