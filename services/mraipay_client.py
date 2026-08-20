"""
Mr Ai Pay (mraipay.top) automated bKash/Nagad/Rocket payment gateway client.

Docs: https://mraipay.top/developers/docs

গুরুত্বপূর্ণ নিরাপত্তা নীতি: payment তৈরির সময় যে payment_url পাওয়া যায় সেটা
ইউজারকে দেওয়া নিরাপদ, কিন্তু payment সম্পন্ন হওয়ার redirect (success_url-এ আসা
query parameter) কখনো নিজে থেকে বিশ্বাস করা হয় না — সবসময় verify_payment()
দিয়ে সরাসরি Mr Ai Pay-এর সার্ভারের কাছ থেকে authoritative status আনা হয়,
কারণ redirect URL যে কেউ ম্যানুয়ালি বানিয়ে হিট করতে পারে।
"""
from __future__ import annotations

from typing import Any

import aiohttp

CREATE_URL = "https://pay.mraipay.top/api/payment/create"
VERIFY_URL = "https://pay.mraipay.top/api/payment/verify"


class MrAiPayError(Exception):
    pass


class MrAiPayClient:
    def __init__(self, api_key: str, secret_key: str, brand_key: str, timeout: int = 20) -> None:
        self.api_key = api_key
        self.secret_key = secret_key
        self.brand_key = brand_key
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "API-KEY": self.api_key,
            "SECRET-KEY": self.secret_key,
            "BRAND-KEY": self.brand_key,
        }

    async def create_payment(
        self, amount: float, cus_name: str, cus_email: str, success_url: str, cancel_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """সফল হলে payment_url ফেরত দেয় — এটাই ইউজারকে পাঠাতে হবে।"""
        body = {
            "cus_name": cus_name,
            "cus_email": cus_email,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "amount": str(amount),
        }
        if metadata:
            body["meta_data"] = metadata  # ⚠️ docs অনুযায়ী ফিল্ডের নাম "meta_data", "metadata" না

        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self._headers()) as http:
                async with http.post(CREATE_URL, json=body) as resp:
                    data = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise MrAiPayError(str(exc)) from exc

        if not data.get("status"):
            raise MrAiPayError(data.get("message", "Payment creation failed"))
        payment_url = data.get("payment_url")
        if not payment_url:
            raise MrAiPayError(f"Unexpected response: {data}")
        return payment_url

    async def verify_payment(self, transaction_id: str) -> dict[str, Any]:
        """
        সরাসরি Mr Ai Pay-এর সার্ভার থেকে authoritative status আনে।
        Response: {status: COMPLETED|PENDING|ERROR, amount, cus_name,
                    transaction_id, metadata, payment_method}
        """
        body = {"transaction_id": transaction_id}
        try:
            async with aiohttp.ClientSession(timeout=self.timeout, headers=self._headers()) as http:
                async with http.post(VERIFY_URL, json=body) as resp:
                    data = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise MrAiPayError(str(exc)) from exc

        if data.get("status") is False:
            raise MrAiPayError(data.get("message", "Verification failed"))
        return data
