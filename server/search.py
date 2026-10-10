from tavily import TavilyClient

from server import config


def search(query: str) -> list[dict]:
    """Top web results for the web_search tool: [{title, url, content}] (FR-5)."""
    # Without a key the Tavily client silently runs keyless; fail loudly instead.
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set")
    client = TavilyClient(api_key=config.TAVILY_API_KEY)
    response = client.search(
        query,
        search_depth="basic",
        max_results=config.SEARCH_MAX_RESULTS,
        timeout=config.SEARCH_TIMEOUT_S,
    )
    return [
        {key: r[key] for key in ("title", "url", "content")}
        for r in response["results"]
    ]
