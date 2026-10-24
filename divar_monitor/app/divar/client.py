from __future__ import annotations

import asyncio
import logging
import random
import time

import httpx

from app.config import Settings
from app.divar.exceptions import (DivarAPIError, DivarBlockedError,
                                  DivarNotFoundError, DivarTransientError)
from app.divar.parser import parse_post_detail, parse_search_response
from app.models import Listing, SearchHit
from app.utils import retry_async

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.divar.ir/v8/postlist/w/search"
POST_URL = "https://api.divar.ir/v8/posts-v2/web/{token}"

DIAGNOSIS = """
================ Divar connectivity ================
Repeated ConnectTimeout to api.divar.ir means the request never
reaches Divar. Measured on a network where this was diagnosed:

  * DNS resolves and TCP :443 connects instantly.
  * TLS to the SAME Divar IP succeeds with SNI=example.com but
    times out with SNI=api.divar.ir  ->  an SNI-based filter.
  * It is selective: digikala.com / eitaa.com / google.com are
    fine, divar.ir and irna.ir are blocked. Not a blanket .ir rule.
  * divar.ir IS reachable from outside the country (a fetch relay
    returns its homepage), so nothing is wrong with Divar.

So Divar is filtered by SNI on this path. Because the filter keys
on the hostname, neither DIVAR_PROXIES nor a different local port
helps while the SNI still says "divar": xray sniffs the plaintext
ClientHello inside the tunnel and routes .ir direct, where the
filter drops it.

Working options, best first:
  1. Route divar.ir through the tunnel instead of direct. In the
     VPN client add a rule BEFORE any geoip/geosite:"ir" rule:
       {"type":"field","domain":["divar.ir"],"outboundTag":"proxy"}
     Then DIVAR_PROXIES can stay empty; traffic rides the tunnel
     and the exit IP is what Divar sees.
  2. Point DIVAR_PROXIES at a proxy you control that exits outside
     the country. SOCKS5 hides the destination from the sniffer,
     so this works where a same-country proxy does not.
  3. Not viable from this process: foreign SNI + Host: api.divar.ir
     reaches Cloudflare but returns 403, and no-SNI times out.
====================================================
"""

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
]


def build_search_payload(query: str, city_ids: list[str], category: str,
                         pagination_data: dict | None = None) -> dict:
    form_data: dict = {"sort": {"str": {"value": "sort_date"}}}  # newest first
    if category:
        form_data["category"] = {"str": {"value": category}}
    return {
        "city_ids": city_ids,
        "pagination_data": pagination_data or {
            "@type": "type.googleapis.com/post_list.PaginationData",
            "page": 1,
            "layer_page": 1,
        },
        "search_data": {"form_data": {"data": form_data}, "query": query},
    }


class DivarClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self._clients: list[tuple[httpx.AsyncClient, str]] = []
        self._rr = 0
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def __aenter__(self) -> "DivarClient":
        # One client per proxy, each with a *sticky* User-Agent (more realistic than
        # changing UA on every request from the same IP).
        for proxy in (self.s.divar_proxies or [None]):
            client = httpx.AsyncClient(
                proxy=proxy,
                timeout=httpx.Timeout(self.s.request_timeout),
                follow_redirects=True,
            )
            self._clients.append((client, random.choice(USER_AGENTS)))
        return self

    async def __aexit__(self, *exc) -> None:
        for client, _ in self._clients:
            await client.aclose()

    # --- internals -----------------------------------------------------
    async def _throttle(self) -> None:
        async with self._lock:
            target = self._last_request + random.uniform(
                self.s.request_delay_min, self.s.request_delay_max)
            wait = target - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    def _next_client(self) -> tuple[httpx.AsyncClient, str]:
        pair = self._clients[self._rr % len(self._clients)]
        self._rr += 1
        return pair

    async def _request(self, method: str, url: str, **kwargs) -> dict:
        async def attempt() -> dict:
            await self._throttle()
            client, ua = self._next_client()  # rotates proxy on every attempt
            headers = {
                "User-Agent": ua,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.6,en;q=0.5",
                "Content-Type": "application/json",
                "Origin": "https://divar.ir",
                "Referer": "https://divar.ir/",
            }
            try:
                resp = await client.request(method, url, headers=headers, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise DivarTransientError(f"{type(exc).__name__}: {exc}") from exc

            code = resp.status_code
            if code in (403, 429):
                raise DivarBlockedError(f"HTTP {code} from {url}")
            if code == 404:
                raise DivarNotFoundError(url)
            if code >= 500:
                raise DivarTransientError(f"HTTP {code}")
            if code >= 400:
                raise DivarAPIError(f"HTTP {code}: {resp.text[:200]}")
            try:
                return resp.json()
            except ValueError as exc:
                raise DivarAPIError("Non-JSON response") from exc

        return await retry_async(
            attempt,
            attempts=self.s.max_retries,
            base_delay=3.0,
            max_delay=120.0,
            retry_on=(DivarTransientError, DivarBlockedError),
            name=f"{method} {url.split('/v8/')[-1][:40]}",
        )

    # --- public API ----------------------------------------------------
    async def preflight(self) -> bool:
        """Fail fast if Divar is unreachable, instead of burning the retry budget.

        Distinguishes 'Divar is down / blocking us' from 'this network filters
        the SNI', which have very different fixes.
        """
        async with httpx.AsyncClient(
                proxy=self.s.divar_proxies[0] if self.s.divar_proxies else None,
                timeout=httpx.Timeout(10.0), follow_redirects=True) as client:
            try:
                # GET / is cheap; a 4xx/5xx still proves we reached the edge.
                await client.get("https://divar.ir/", headers={"User-Agent": USER_AGENTS[0]})
                return True
            except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ReadTimeout):
                log.error("Cannot reach Divar at all.%s", DIAGNOSIS)
                return False
            except Exception as exc:            # noqa: BLE001 - any other failure
                log.warning("Divar preflight inconclusive (%s); continuing.", exc)
                return True

    async def search(self, query: str) -> list[SearchHit]:
        hits: list[SearchHit] = []
        pagination_data: dict | None = None
        for _ in range(self.s.max_pages):
            payload = build_search_payload(
                query, self.s.city_ids, self.s.category, pagination_data)
            data = await self._request("POST", SEARCH_URL, json=payload)
            hits.extend(parse_search_response(data))
            pagination = data.get("pagination") or {}
            if not pagination.get("has_next_page") or not pagination.get("data"):
                break
            pagination_data = pagination["data"]  # echo back server-issued cursor
        return hits

    async def get_listing(self, hit: SearchHit) -> Listing:
        data = await self._request("GET", POST_URL.format(token=hit.token))
        d = parse_post_detail(data)
        return Listing(
            token=hit.token,
            title=d["title"] or hit.title,
            price=d["price"] or hit.price,
            location=d["location"] or hit.location,
            description=d["description"],
            image_urls=d["images"] or ([hit.thumbnail] if hit.thumbnail else []),
        )
