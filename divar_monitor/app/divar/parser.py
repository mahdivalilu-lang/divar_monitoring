from __future__ import annotations

from typing import Any

from app.divar.exceptions import DivarAPIError
from app.models import SearchHit

# Invisible bidi controls Divar prepends to numbers, e.g. "\u200f۹۰۰,۰۰۰ تومان".
# They render as stray glyphs in Telegram, so strip them from displayed text.
_BIDI = "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"


def _clean(value: Any) -> str | None:
    """Normalise a display string: strip bidi controls and surrounding whitespace.

    Returns None (not "") for a missing value so SearchHit.price / .location keep
    their documented `str | None` contract and Telegram omits the line entirely.
    """
    if not isinstance(value, str):
        return None
    return value.translate({ord(c): None for c in _BIDI}).strip() or None


def _g(d: Any, *path: str, default=None):
    """Safe nested get."""
    for key in path:
        if not isinstance(d, dict):
            return default
        d = d.get(key, default)
    return d


def parse_search_response(data: dict) -> list[SearchHit]:
    """
    Search response. Divar renamed the list key; accept both, newest first.

    Live shape (captured 2026-10-18):
      {"list_top_widgets": [...], "list_widgets": [{"widget_type": "POST_ROW",
        "data": {"token": "...", "title": "...", "middle_description_text": "<price>",
                 "bottom_description_text": "<time>", "image_url": "...",
                 "action": {"payload": {"token": "..."}}}}],
       "pagination": {"has_next_page": true, "data": {...}}, ...}

    NOTE: "description" no longer carries the price on POST_ROW; it is now
    "middle_description_text" (present on 24/24 live rows).
    """
    widgets = data.get("list_widgets")
    if widgets is None:
        widgets = data.get("widget_list")      # legacy shape
    if widgets is None:
        raise DivarAPIError(f"Unexpected search schema, keys={list(data)[:10]}")

    hits: list[SearchHit] = []
    for widget in widgets:
        wd = widget.get("data") or {}
        token = wd.get("token") or _g(wd, "action", "payload", "token")
        if not token or not wd.get("title"):
            continue  # ads, banners, "suggested" rows etc.
        hits.append(SearchHit(
            token=token,
            title=wd["title"].strip(),
            price=_clean(wd.get("description") or wd.get("middle_description_text")
                         or wd.get("red_text")),
            location=_clean(wd.get("bottom_description_text")
                            or _g(wd, "action", "payload", "web_info", "city_persian")),
            thumbnail=wd.get("image_url") or wd.get("thumbnail"),
        ))
    return hits


def parse_post_detail(data: dict) -> dict:
    """
    Post detail (observed shape): {"sections": [{"section_name": "...",
      "widgets": [{"widget_type": "...", "data": {...}}]}], "webengage": {...}}
    Returns a dict with title, description, price, location, images.
    """
    out: dict[str, Any] = {"title": None, "description": "", "price": None,
                           "location": None, "images": []}

    for section in data.get("sections") or []:
        section_name = (section.get("section_name") or "").upper()
        for widget in section.get("widgets") or []:
            wtype, wd = widget.get("widget_type"), widget.get("data") or {}

            if wtype == "IMAGE_CAROUSEL":
                for item in wd.get("items") or []:
                    url = _g(item, "image", "url")
                    if url:
                        out["images"].append(url)
            elif wtype == "DESCRIPTION_ROW":
                out["description"] = (wd.get("text") or "").strip()
            elif wtype == "TITLE_ROW":
                # The DESCRIPTION section also contains a TITLE_ROW whose text is
                # just the section label ("توضیحات"). The real title lives in the
                # TITLE section as LEGEND_TITLE_ROW. Keep the first non-label one.
                text = (wd.get("text") or "").strip()
                if text and section_name != "DESCRIPTION" and not out["title"]:
                    out["title"] = text
            elif wtype == "LEGEND_TITLE_ROW":
                text = (wd.get("title") or wd.get("text") or "").strip()
                if text:
                    out["title"] = text
            elif wtype in {"UNEXPANDABLE_ROW", "EXPANDABLE_ROW"}:
                label = _clean(wd.get("title"))
                if label.startswith("قیمت") and not out["price"]:
                    out["price"] = _clean(wd.get("value")) or None

    meta = data.get("webengage") or {}
    if not out["price"] and meta.get("price"):
        out["price"] = f"{int(meta['price']):,} تومان"
    city, district = meta.get("city"), meta.get("district")
    # webengage.city is an English slug ("urmia"); prefer the Persian name when
    # the post carries one so alerts read naturally.
    city_fa = (_g(data, "city", "name") or _g(data, "contact", "city")
               or meta.get("city_persian"))
    out["location"] = "، ".join(
        str(x).strip() for x in (city_fa or city, district) if x and str(x).strip()
    ) or None
    out["images"] = list(dict.fromkeys(out["images"]))  # de-dupe, keep order
    return out
