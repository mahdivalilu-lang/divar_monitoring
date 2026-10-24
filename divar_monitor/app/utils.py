from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)


async def retry_async(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    name: str = "operation",
) -> T:
    """Exponential backoff with jitter. Honors `exc.retry_after` if present (e.g. Telegram 429)."""
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except retry_on as exc:
            if attempt == attempts:
                raise
            delay = getattr(exc, "retry_after", None)
            if delay is None:
                delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                delay += random.uniform(0, delay * 0.25)
            log.warning("%s failed (%s/%s): %s - retrying in %.1fs",
                        name, attempt, attempts, exc, delay)
            await asyncio.sleep(delay)
    raise RuntimeError("unreachable")


_ARABIC_TO_PERSIAN = str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه"})
_WS = re.compile(r"[\s\u200c\u200f\u200e]+")  # whitespace, ZWNJ, RTL/LTR marks


def normalize_fa(text: str) -> str:
    """Normalise Persian/Arabic character variants for reliable keyword matching."""
    return _WS.sub(" ", text.translate(_ARABIC_TO_PERSIAN)).strip().lower()
