from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bot.agent.context import SourceItem


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src"}


def canonical_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = re.sub(r"/+$", "", parts.path or "/")
    query_items = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in TRACKING_KEYS and not any(k.startswith(prefix) for prefix in TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def normalize_title(title: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    for suffix in (" coindesk", " cointelegraph", " decrypt"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def content_hash(item: SourceItem) -> str:
    text = " ".join([item.title or "", item.snippet or "", item.content or ""]).strip().lower()
    return hashlib.sha1(re.sub(r"\s+", " ", text).encode("utf-8")).hexdigest()


def dedupe_sources(items: list[SourceItem], fuzzy_threshold: float = 0.92) -> list[SourceItem]:
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    seen_hashes: set[str] = set()
    result: list[SourceItem] = []

    for item in items:
        c_url = canonical_url(item.url)
        n_title = normalize_title(item.title)
        h = content_hash(item)
        if c_url and c_url in seen_urls:
            continue
        if n_title and n_title in seen_titles:
            continue
        if h in seen_hashes:
            continue
        if n_title and any(SequenceMatcher(None, n_title, old).ratio() >= fuzzy_threshold for old in seen_titles):
            continue
        if c_url:
            seen_urls.add(c_url)
            item.url = c_url
        if n_title:
            seen_titles.append(n_title)
        seen_hashes.add(h)
        result.append(item)

    return result
