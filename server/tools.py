from datetime import datetime

from server import search, store

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
    },
    {
        "name": "add_note",
        "description": "Save a note. Repeat the stored note back to the user.",
        "parameters_json_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "The note text"}},
            "required": ["text"],
        },
    },
    {
        "name": "list_notes",
        "description": "List every saved note, newest first.",
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
]


def _web_search(args: dict, now: datetime) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"error": "web_search needs a non-empty text query"}
    try:
        return {"results": search.search(query)}
    # Tavily errors share no base class, and a tool must never crash the loop (FR-7).
    except Exception as e:  # noqa: BLE001
        return {"error": f"web search failed: {e}"}


def _add_note(args: dict, now: datetime) -> dict:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"error": "add_note needs a non-empty text"}
    return store.add_note(text, now.isoformat(timespec="seconds"))


def _list_notes(args: dict, now: datetime) -> dict:
    return {"notes": store.list_notes()}


_HANDLERS = {
    "web_search": _web_search,
    "add_note": _add_note,
    "list_notes": _list_notes,
}


def run(name: str, args: dict, now: datetime) -> dict:
    """Run one tool call; always returns a result dict, never raises (FR-7)."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    if not isinstance(args, dict):
        return {"error": f"{name}: arguments must be an object"}
    return handler(args, now)
