from datetime import datetime

from server import search

DECLARATIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for live or current information such as news, weather, prices "
            "or scores. The query must never contain note or reminder content."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "A short web search query"}
            },
            "required": ["query"],
        },
    }
]


def _web_search(args: dict) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"error": "web_search needs a non-empty text query"}
    try:
        return {"results": search.search(query)}
    # Tavily errors share no base class, and a tool must never crash the loop (FR-7).
    except Exception as e:  # noqa: BLE001
        return {"error": f"web search failed: {e}"}


_HANDLERS = {"web_search": _web_search}


def run(name: str, args: dict, now: datetime) -> dict:
    """Run one tool call; always returns a result dict, never raises (FR-7)."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    if not isinstance(args, dict):
        return {"error": f"{name}: arguments must be an object"}
    return handler(args)
