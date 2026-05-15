"""
ProbeAI — URL content fetcher.

Optional enrichment: fetch full page content from URLs
when snippets from search results aren't enough.
"""

from __future__ import annotations

import requests
from utils import log


def fetch_url_content(url: str, timeout: int = 10, max_chars: int = 5000) -> str:
    """
    Fetch the text content of a URL.
    Returns truncated plain text, or empty string on failure.
    """
    try:
        log.debug(f"Fetching URL: {url}")
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "ProbeAI/1.0 (research agent)"},
        )
        resp.raise_for_status()

        # Simple extraction: just get the text content
        # For a minimal agent, search snippets are usually sufficient
        text = resp.text

        # Strip HTML tags (very basic)
        import re
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return text[:max_chars]

    except Exception as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return ""


def batch_fetch(urls: list[str], max_urls: int = 5) -> dict[str, str]:
    """
    Fetch content from multiple URLs.
    Returns a dict of {url: content}.
    """
    results = {}
    for url in urls[:max_urls]:
        content = fetch_url_content(url)
        if content:
            results[url] = content
    return results
