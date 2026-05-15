"""
ProbeAI — Search service.

Wraps the Tavily API for web search.
"""

from __future__ import annotations

from tavily import TavilyClient

import config
from models.schemas import SearchResult
from utils import log


def _get_client() -> TavilyClient:
    """Create a Tavily client."""
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set. Add it to your .env file.")
    return TavilyClient(api_key=config.TAVILY_API_KEY)


def search(
    query: str,
    max_results: int = config.SEARCH_RESULTS_PER_QUERY,
) -> list[SearchResult]:
    """
    Run a single search query via Tavily.
    Returns a list of SearchResult objects.
    """
    log.info(f"🔍 Searching: {query}")
    client = _get_client()

    try:
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_answer=False,
        )
    except Exception as e:
        log.error(f"Search failed for '{query}': {e}")
        return []

    results = []
    for item in response.get("results", []):
        results.append(
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", ""),
                score=item.get("score", 0.0),
            )
        )

    log.info(f"   → {len(results)} results found")
    return results


def batch_search(
    queries: list[str],
    max_results_per_query: int = config.SEARCH_RESULTS_PER_QUERY,
    max_queries: int = config.MAX_QUERIES_PER_ITERATION,
) -> list[SearchResult]:
    """
    Run multiple search queries and deduplicate results by URL.
    """
    queries = queries[:max_queries]
    all_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    for query in queries:
        results = search(query, max_results=max_results_per_query)
        for result in results:
            if result.url not in seen_urls:
                seen_urls.add(result.url)
                all_results.append(result)

    log.info(f"📊 Batch search: {len(queries)} queries → {len(all_results)} unique results")
    return all_results
