"""SoldComps client (§4.2).

Implements the details that "fast alle falsch machen":

  1. Pagination is mandatory. Each request returns ONE page. Drive pagination
     purely off `hasNextPage`. `totalItems` is the count on the CURRENT page,
     NOT the grand total — never use it for control flow. The real total is
     `totalResults` (a String, because eBay approximates); exposed for display.
  2. `hydrateBoa=true` is mandatory on every sold query, otherwise `soldPrice`
     on best-offer sales is the ASK price, not the paid price. `boaHydrated` is
     kept per item.
  3. `X-Credit-Source: subscription-only` on scheduled batch jobs so they stop
     cleanly at the monthly limit instead of burning credits.
  4. Optional `X-eBay-Cookies` lifts pages to 200 items — SEPARATE eBay account
     only, >= 2-3s between requests. Off by default.
  5. 429 handling: code == "quota_exceeded" -> do not retry, alert. Otherwise
     respect Retry-After.
  6. soldAfter/soldBefore are post-processing filters — they save NO quota, so
     this client does not rely on them for cost control.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import httpx

from app.clients.exceptions import ClientError, QuotaExceededError, RateLimitError
from app.config import get_settings

# Safety cap so a misbehaving `hasNextPage` can never loop forever.
_MAX_PAGES = 1000


@dataclass
class ScrapePage:
    """One page of a scrape response."""

    items: list[dict]
    has_next_page: bool
    page: int
    # Real approximate grand total (String from the API). Display only.
    total_results: str | None = None
    raw: dict = field(default_factory=dict)


class SoldCompsClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        ebay_site: str | None = None,
        credit_source: str | None = None,
        use_cookies: bool | None = None,
        ebay_cookies: str | None = None,
        cookie_min_interval: float | None = None,
        max_requests_per_minute: int | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.soldcomps_api_key
        self.base_url = (base_url or settings.soldcomps_base_url).rstrip("/")
        self.ebay_site = ebay_site or settings.soldcomps_ebay_site
        self.credit_source = (
            credit_source
            if credit_source is not None
            else settings.soldcomps_credit_source
        )
        self.use_cookies = (
            settings.soldcomps_use_cookies if use_cookies is None else use_cookies
        )
        self.ebay_cookies = (
            ebay_cookies if ebay_cookies is not None else settings.soldcomps_ebay_cookies
        )
        self.cookie_min_interval = (
            cookie_min_interval
            if cookie_min_interval is not None
            else settings.soldcomps_cookie_min_interval
        )
        max_rpm = (
            max_requests_per_minute
            if max_requests_per_minute is not None
            else settings.soldcomps_max_requests_per_minute
        )
        # Minimum spacing between requests to stay under the rate limit (§4.2.5).
        self._min_interval = 60.0 / max_rpm if max_rpm > 0 else 0.0
        if self.use_cookies:
            self._min_interval = max(self._min_interval, self.cookie_min_interval)

        self._sleep = sleep
        self._monotonic = monotonic
        self._last_request_at: float | None = None

        headers = {"Authorization": f"Bearer {self.api_key}"}
        self._client = httpx.Client(
            base_url=self.base_url, transport=transport, timeout=timeout, headers=headers
        )
        # Count HTTP requests made so callers can record per-request cost.
        self.request_count = 0

    def __enter__(self) -> "SoldCompsClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- internal ----------------------------------------------------------

    def _throttle(self) -> None:
        if self._min_interval <= 0 or self._last_request_at is None:
            return
        elapsed = self._monotonic() - self._last_request_at
        wait = self._min_interval - elapsed
        if wait > 0:
            self._sleep(wait)

    def _extra_headers(self, *, batch: bool) -> dict[str, str]:
        headers: dict[str, str] = {}
        # subscription-only for scheduled batch jobs (§4.2.3).
        if batch and self.credit_source:
            headers["X-Credit-Source"] = self.credit_source
        if self.use_cookies and self.ebay_cookies:
            headers["X-eBay-Cookies"] = self.ebay_cookies
        return headers

    @staticmethod
    def _raise_for_429(resp: httpx.Response) -> None:
        code: str | None = None
        try:
            body = resp.json()
            if isinstance(body, dict):
                code = body.get("code")
        except (json.JSONDecodeError, ValueError):
            pass
        if code == "quota_exceeded":
            # Monthly contingent spent — do NOT retry, alert (§4.2.5).
            raise QuotaExceededError("SoldComps quota exceeded")
        retry_after_hdr = resp.headers.get("Retry-After")
        retry_after: float | None = None
        if retry_after_hdr is not None:
            try:
                retry_after = float(retry_after_hdr)
            except ValueError:
                retry_after = None
        raise RateLimitError("SoldComps rate limited", retry_after=retry_after)

    def _get(self, path: str, params: dict, *, batch: bool) -> dict:
        self._throttle()
        self.request_count += 1
        try:
            resp = self._client.get(
                path, params=params, headers=self._extra_headers(batch=batch)
            )
        finally:
            self._last_request_at = self._monotonic()
        if resp.status_code == 429:
            self._raise_for_429(resp)
        if resp.status_code >= 400:
            # Surface SoldComps' own explanation (bad parameter, plan limit,
            # unsupported site, ...). Without it a 400 is unfixable guesswork.
            raise ClientError(
                f"SoldComps error {resp.status_code} on {path}: {resp.text[:400]}"
            )
        return resp.json()

    # -- public ------------------------------------------------------------

    def scrape_page(
        self,
        query: str,
        *,
        sold: bool,
        page: int = 1,
        ebay_site: str | None = None,
        seller_type: str | None = None,
        aspect_filter: dict | None = None,
        batch: bool = True,
    ) -> ScrapePage:
        """Fetch a single page of /v1/scrape."""
        params: dict[str, object] = {
            # Der Parameter heisst "keyword". Mit "query" antwortet die API auf
            # JEDEN Aufruf mit 400 ZodError ('path: ["keyword"], Required') —
            # ein einziges falsches Wort legte die gesamte Verkaufsseite lahm.
            "keyword": query,
            "sold": "true" if sold else "false",
            "ebaySite": ebay_site or self.ebay_site,
            "page": page,
        }
        if sold:
            # Mandatory: without it soldPrice is the ask on best-offer sales.
            params["hydrateBoa"] = "true"
        if seller_type:
            params["sellerType"] = seller_type
        if aspect_filter:
            params["aspectFilter"] = json.dumps(aspect_filter, ensure_ascii=False)

        body = self._get("/v1/scrape", params, batch=batch)
        items = body.get("items") or []
        total_results = body.get("totalResults")
        return ScrapePage(
            items=list(items),
            has_next_page=bool(body.get("hasNextPage", False)),
            page=page,
            total_results=str(total_results) if total_results is not None else None,
            raw=body,
        )

    def iter_scrape(
        self,
        query: str,
        *,
        sold: bool,
        ebay_site: str | None = None,
        seller_type: str | None = None,
        aspect_filter: dict | None = None,
        batch: bool = True,
        max_pages: int = _MAX_PAGES,
    ) -> Iterator[dict]:
        """Paginate /v1/scrape, yielding every item across pages.

        Pagination stops when `hasNextPage` is false (never on `totalItems`).
        """
        page = 1
        while page <= max_pages:
            result = self.scrape_page(
                query,
                sold=sold,
                page=page,
                ebay_site=ebay_site,
                seller_type=seller_type,
                aspect_filter=aspect_filter,
                batch=batch,
            )
            for item in result.items:
                yield item
            if not result.has_next_page:
                return
            page += 1

    def scrape_sold(
        self,
        query: str,
        *,
        ebay_site: str | None = None,
        seller_type: str | None = None,
        aspect_filter: dict | None = None,
        batch: bool = True,
        max_pages: int = _MAX_PAGES,
    ) -> list[dict]:
        """All real sold comps for a query (hydrateBoa always on)."""
        return list(
            self.iter_scrape(
                query,
                sold=True,
                ebay_site=ebay_site,
                seller_type=seller_type,
                aspect_filter=aspect_filter,
                batch=batch,
                max_pages=max_pages,
            )
        )

    def scrape_ask(
        self,
        query: str,
        *,
        ebay_site: str | None = None,
        batch: bool = True,
        max_pages: int = _MAX_PAGES,
    ) -> list[dict]:
        """Ask-side listings (sold=false): currentPrice, watcherCount, etc."""
        return list(
            self.iter_scrape(
                query,
                sold=False,
                ebay_site=ebay_site,
                batch=batch,
                max_pages=max_pages,
            )
        )

    def get_item(self, item_id: str, *, include_description: bool = True) -> dict:
        """Candidate detail: all 1600px images, full itemSpecifics, seller data."""
        params = {"includeDescription": "true" if include_description else "false"}
        return self._get(f"/v1/item/{item_id}", params, batch=True)
