from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


DEFAULT_KEYWORDS = (
    "گردو,مغز گردو,گردو با پوست,گردوی کاغذی,"
    "بادام,مغز بادام,بادام درختی,بادام زمینی,بادام هندی,بادام منقا,"
    "کشمش,مویز,کشمش پلویی,کشمش سبز,توت خشک,انجیر خشک,"
    "برگه زردآلو,قیسی,برگه هلو,میوه خشک,لواشک,"
    "آجیل,پسته,مغز پسته,فندق,مغز فندق,نخودچی,تخمه,تخمه کدو,تخمه آفتابگردان"
)


def _csv(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_proxy: str | None
    telegram_api_base: str

    # Search
    keywords: list[str]
    city_ids: list[str]
    category: str
    strict_match: bool

    # Polling
    poll_interval: float
    poll_jitter: float
    max_pages: int

    # HTTP / anti-blocking
    request_delay_min: float
    request_delay_max: float
    request_timeout: float
    max_retries: int
    divar_proxies: list[str]

    # Alerts / storage
    max_images: int
    seed_on_first_run: bool
    db_path: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Settings":
        keywords = _csv("KEYWORDS", DEFAULT_KEYWORDS)
        if not keywords:
            raise RuntimeError("KEYWORDS must contain at least one keyword")
        return cls(
            telegram_bot_token=_required("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=_required("TELEGRAM_CHAT_ID"),
            telegram_proxy=os.getenv("TELEGRAM_PROXY") or None,
            telegram_api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
            keywords=keywords,
            city_ids=_csv("CITY_IDS", "4"),
            category=os.getenv("CATEGORY", "").strip(),
            strict_match=_bool("STRICT_MATCH", True),
            poll_interval=float(os.getenv("POLL_INTERVAL_SECONDS", "180")),
            poll_jitter=float(os.getenv("POLL_JITTER_SECONDS", "45")),
            max_pages=int(os.getenv("MAX_PAGES", "2")),
            request_delay_min=float(os.getenv("REQUEST_DELAY_MIN", "2.0")),
            request_delay_max=float(os.getenv("REQUEST_DELAY_MAX", "6.0")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT", "20")),
            max_retries=int(os.getenv("MAX_RETRIES", "4")),
            divar_proxies=_csv("DIVAR_PROXIES"),
            max_images=int(os.getenv("MAX_IMAGES", "5")),
            seed_on_first_run=_bool("SEED_ON_FIRST_RUN", True),
            db_path=Path(os.getenv("DB_PATH", "data/seen_posts.db")),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )
