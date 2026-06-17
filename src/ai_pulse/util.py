"""Small shared helpers."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# Tracking params stripped during URL normalisation so the same story shared
# with different campaign tags is recognised as a duplicate.
_TRACKING_PREFIXES = ("utm_", "mc_", "fbclid", "gclid", "ref", "ref_src",
                      "spm", "cmpid", "_hsenc", "_hsmi")


def normalize_url(url: str) -> str:
    """Canonicalise a URL for dedup comparison.

    - lowercases scheme + host, drops `www.`
    - removes tracking query params
    - drops fragments and trailing slashes
    """
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()

    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    kept = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
        if not any(k.lower().startswith(pre) for pre in _TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(kept))

    path = p.path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, "", query, ""))
