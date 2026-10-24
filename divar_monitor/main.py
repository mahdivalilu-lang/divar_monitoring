from __future__ import annotations

import asyncio
import logging
import random
import signal

from app.config import Settings
from app.divar.client import DivarClient
from app.divar.exceptions import (DivarBlockedError, DivarError,
                                  DivarNotFoundError)
from app.storage import Storage
from app.telegram import TelegramError, TelegramNotifier
from app.utils import normalize_fa

log = logging.getLogger("divar_monitor")


def find_keyword(text: str, keywords: list[str]) -> str | None:
    norm = normalize_fa(text)
    for kw in keywords:
        if normalize_fa(kw) in norm:
            return kw
    return None


async def run_cycle(s: Settings, divar: DivarClient, store: Storage,
                    tg: TelegramNotifier, seeding: bool) -> int:
    sent = 0
    seen_this_cycle: set[str] = set()

    for keyword in s.keywords:
        hits = await divar.search(keyword)
        log.info("Keyword %r -> %d results", keyword, len(hits))

        for hit in hits:
            if hit.token in seen_this_cycle or await store.is_seen(hit.token):
                continue
            seen_this_cycle.add(hit.token)

            if seeding:  # first run: record the backlog without spamming
                await store.mark(hit.token, hit.title, "seeded")
                continue

            try:
                listing = await divar.get_listing(hit)
            except DivarNotFoundError:
                await store.mark(hit.token, hit.title, "skipped")
                continue

            matched = find_keyword(f"{listing.title} {listing.description}", s.keywords)
            if s.strict_match and not matched:
                await store.mark(hit.token, hit.title, "skipped")
                continue
            listing.matched_keyword = matched or keyword

            try:
                await tg.send_listing(listing)
            except TelegramError as exc:
                # Don't mark as seen -> it will be retried next cycle.
                log.error("Telegram delivery failed for %s: %s", hit.token, exc)
                continue

            await store.mark(hit.token, listing.title, "notified")
            sent += 1
            log.info("Notified: %s (%s)", listing.title, listing.url)
            await asyncio.sleep(random.uniform(1.0, 2.5))  # stay under Telegram limits
    return sent


async def main() -> None:
    s = Settings.from_env()
    logging.basicConfig(
        level=s.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            signal.signal(sig, lambda *_: stop.set())

    async with DivarClient(s) as divar, TelegramNotifier(s) as tg, Storage(s.db_path) as store:
        # Fail fast and loudly if Divar is unreachable, rather than looping
        # through retries that can never succeed. See DivarClient.preflight().
        if not await divar.preflight():
            log.error("Divar is unreachable from this network. Not starting the "
                      "polling loop. See the DIAGNOSIS block in app/divar/client.py.")
            return

        seeding = s.seed_on_first_run and await store.count() == 0
        if seeding:
            log.info("Empty database: first cycle will seed existing posts silently")

        failures = 0
        cycles = 0
        while not stop.is_set():
            try:
                sent = await run_cycle(s, divar, store, tg, seeding)
                log.info("Cycle done, %d alert(s) sent", sent)
                seeding, failures = False, 0
                cycles += 1
                if cycles % 500 == 0:
                    await store.prune()
                delay = s.poll_interval + random.uniform(0, s.poll_jitter)
            except DivarBlockedError as exc:
                failures += 1
                delay = min(1800, s.poll_interval * 2 ** failures)  # long backoff
                log.error("Blocked by Divar (%s). Backing off %.0fs", exc, delay)
            except DivarError as exc:
                failures += 1
                delay = min(600, s.poll_interval * (1 + failures))
                log.error("Divar error: %s. Next attempt in %.0fs", exc, delay)
            except Exception:
                failures += 1
                delay = min(600, s.poll_interval * (1 + failures))
                log.exception("Unexpected error in cycle")

            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    log.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
