"""Canonical forms used for Citation identity and deduplication."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DOI_PREFIX = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
_TRACKING_QUERY_KEYS = {"fbclid", "gclid"}


def normalize_doi(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = _DOI_PREFIX.sub("", value.strip()).strip().casefold()
    return normalized or None


def normalize_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    raw = value.strip()
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in _TRACKING_QUERY_KEYS
        ]
    )
    path = parts.path.rstrip("/") or ""
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, query, "")
    )


def utf8_safe_text(value: str) -> str:
    """Return text that can be encoded as UTF-8.

    PDF extractors sometimes emit UTF-16 surrogate code points as Python
    characters. Strict ``str.encode("utf-8")`` rejects those, including with
    ``errors="replace"``. A UTF-16 round-trip reassembles valid pairs and
    replaces lone surrogates.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return value


def citation_key(title: str, year: int | None) -> str:
    words = re.findall(r"[a-z0-9]+", title.casefold())
    stem = "-".join(words[:5]) or "citation"
    return f"{stem}-{year}" if year else stem
