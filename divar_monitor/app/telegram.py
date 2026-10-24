from __future__ import annotations

import html
import logging

import httpx

from app.config import Settings
from app.models import Listing
from app.utils import retry_async

log = logging.getLogger(__name__)


class TelegramError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class TelegramBadRequest(TelegramError):
    """400 - not retryable (e.g. Telegram could not fetch the image URL)."""


class TelegramNotifier:
    def __init__(self, settings: Settings):
        self.s = settings
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "TelegramNotifier":
        self._client = httpx.AsyncClient(
            proxy=self.s.telegram_proxy, timeout=httpx.Timeout(30.0))
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    # --- formatting ----------------------------------------------------
    @staticmethod
    def format_caption(item: Listing, limit: int) -> str:
        e = html.escape
        lines = [f"🌰 <b>{e(item.title)}</b>", ""]
        if item.price:
            lines.append(f"💰 {e(item.price)}")
        if item.location:
            lines.append(f"📍 {e(item.location)}")
        if item.matched_keyword:
            lines.append(f"🔎 {e(item.matched_keyword)}")
        footer = f'\n🔗 <a href="{item.url}">مشاهده در دیوار</a>'
        desc = item.description.strip()
        room = limit - len("\n".join(lines)) - len(footer) - 10
        if desc and room > 50:
            if len(desc) > room:
                desc = desc[: room - 1].rstrip() + "…"
            lines += ["", e(desc)]
        return "\n".join(lines) + footer

    # --- transport -----------------------------------------------------
    async def _call(self, method: str, payload: dict) -> dict:
        url = f"{self.s.telegram_api_base}/bot{self.s.telegram_bot_token}/{method}"

        async def attempt() -> dict:
            try:
                resp = await self._client.post(url, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise TelegramError(f"network: {exc}") from exc
            try:
                body = resp.json()
            except ValueError:
                body = {}
            if resp.status_code == 200 and body.get("ok"):
                return body
            desc = body.get("description", resp.text[:200])
            if resp.status_code == 429:
                wait = body.get("parameters", {}).get("retry_after", 5)
                raise TelegramError(f"rate limited: {desc}", retry_after=float(wait) + 1)
            if resp.status_code == 400:
                raise TelegramBadRequest(desc)
            raise TelegramError(f"HTTP {resp.status_code}: {desc}")

        return await retry_async(
            attempt, attempts=5, base_delay=2.0, max_delay=60.0,
            retry_on=(TelegramError,), name=f"telegram.{method}")
        # note: TelegramBadRequest is a subclass; handled by caller before retry is useful

    async def _send_text(self, item: Listing) -> None:
        await self._call("sendMessage", {
            "chat_id": self.s.telegram_chat_id,
            "text": self.format_caption(item, 4000),
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        })

    async def send_listing(self, item: Listing) -> None:
        images = item.image_urls[: self.s.max_images]
        try:
            if len(images) == 1:
                await self._call("sendPhoto", {
                    "chat_id": self.s.telegram_chat_id,
                    "photo": images[0],
                    "caption": self.format_caption(item, 1024),
                    "parse_mode": "HTML",
                })
            elif len(images) > 1:
                media = [{"type": "photo", "media": url} for url in images]
                media[0]["caption"] = self.format_caption(item, 1024)
                media[0]["parse_mode"] = "HTML"
                await self._call("sendMediaGroup", {
                    "chat_id": self.s.telegram_chat_id, "media": media})
            else:
                await self._send_text(item)
        except TelegramBadRequest as exc:
            # Typically "failed to get HTTP URL content": fall back to plain text alert.
            log.warning("Media send rejected (%s); falling back to text", exc)
            await self._send_text(item)
