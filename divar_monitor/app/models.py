from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchHit:
    """A lightweight row from the search list."""
    token: str
    title: str
    price: str | None = None
    location: str | None = None
    thumbnail: str | None = None


@dataclass
class Listing:
    """Fully-resolved post, ready for alerting."""
    token: str
    title: str
    price: str | None
    location: str | None
    description: str
    image_urls: list[str] = field(default_factory=list)
    matched_keyword: str | None = None

    @property
    def url(self) -> str:
        return f"https://divar.ir/v/{self.token}"
