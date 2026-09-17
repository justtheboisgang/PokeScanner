"""eBay Browse API client (§4.3).

Official, free, ~5000 calls/day at the application level. Used for ACTIVE
listings as a sourcing channel. Auth is OAuth2 client-credentials (application
token), cached until shortly before expiry.
"""

from __future__ import annotations

import base64
import time

import httpx

from app.clients.exceptions import QuotaExceededError, RateLimitError
from app.config import get_settings

_SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayBrowseClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        *,
        base_url: str | None = None,
        oauth_url: str | None = None,
        marketplace: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        monotonic=time.monotonic,
    ) -> None:
        settings = get_settings()
        self.client_id = client_id if client_id is not None else settings.ebay_client_id
        self.client_secret = (
            client_secret if client_secret is not None else settings.ebay_client_secret
        )
        self.base_url = (base_url or settings.ebay_browse_base_url).rstrip("/")
        self.oauth_url = oauth_url or settings.ebay_oauth_url
        self.marketplace = marketplace or settings.ebay_marketplace
        self.sort = settings.ebay_browse_sort
        self._client = httpx.Client(transport=transport, timeout=timeout)
        self._monotonic = monotonic
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def __enter__(self) -> "EbayBrowseClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _get_token(self) -> str:
        if self._token is not None and self._monotonic() < self._token_expiry:
            return self._token
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        resp = self._client.post(
            self.oauth_url,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials", "scope": _SCOPE},
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        # Refresh 60s before the stated expiry.
        self._token_expiry = self._monotonic() + float(body.get("expires_in", 7200)) - 60
        return self._token

    def search_active(
        self, query: str, *, limit: int = 50, sort: str | None = None
    ) -> list[dict]:
        """Search active listings; returns the itemSummaries list.

        `sort` matters more than it looks: without it eBay ranks by relevance,
        so a brand-new listing that scores poorly never reaches the first page
        and the scanner never sees it. "newlyListed" puts the freshest first,
        which is what a deal hunter needs (R1).
        """
        token = self._get_token()
        params: dict[str, object] = {"q": query, "limit": limit}
        chosen = self.sort if sort is None else sort
        if chosen:
            params["sort"] = chosen
        resp = self._client.get(
            f"{self.base_url}/buy/browse/v1/item_summary/search",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
            },
        )
        if resp.status_code == 429:
            raise RateLimitError("eBay rate limited")
        if resp.status_code == 403:
            # Daily application quota exhausted.
            raise QuotaExceededError("eBay Browse quota/permission error (403)")
        resp.raise_for_status()
        body = resp.json()
        return list(body.get("itemSummaries") or [])
