from datetime import datetime
from zoneinfo import ZoneInfo

from server import config, search, store

# Larger integers can't be bound as SQLite parameters (OverflowError).
SQLITE_MAX_INT = 2**63 - 1

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
        "name": "add_reminder",
        "description": (
            "Set a reminder. due_at is an exact ISO 8601 time with offset, e.g. "
            "2026-10-10T17:00:00+05:30, worked out from the current time. "
            "Repeat the stored reminder back to the user."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to be reminded of"},
                "due_at": {
                    "type": "string",
                    "description": "ISO 8601 time with offset",
                },
            },
            "required": ["text", "due_at"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List every pending reminder by due time, with its id.",
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_reminder",
        "description": (
            "Cancel a pending reminder by its id. To cancel by description, call "
            "list_reminders first and use the id of the matching reminder."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Id from list_reminders"}
            },
            "required": ["id"],
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


def _add_reminder(args: dict, now: datetime) -> dict:
    text = args.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"error": "add_reminder needs a non-empty text"}
    try:
        due = datetime.fromisoformat(args["due_at"])
    except (KeyError, TypeError, ValueError):
        return {"error": "add_reminder needs due_at as an ISO 8601 time"}
    if due.tzinfo is None:
        return {"error": "due_at needs a UTC offset, e.g. +05:30"}
    if due < now:
        return {"error": "due_at is in the past"}
    due_at = due.astimezone(ZoneInfo(config.TIMEZONE)).isoformat(timespec="seconds")
    reminder = store.add_reminder(text, due_at, now.isoformat(timespec="seconds"))
    return {**reminder, "due_spoken": spoken_when(due, now)}


def _list_reminders(args: dict, now: datetime) -> dict:
    return {
        "reminders": [
            {**r, "due_spoken": spoken_when(datetime.fromisoformat(r["due_at"]), now)}
            for r in store.list_pending()
        ]
    }


def _reminder_id(value: object) -> int | None:
    # Gemini may send 3.0 for 3; bool is an int subclass but never an id.
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int) and abs(value) <= SQLITE_MAX_INT:
        return value
    return None


def _cancel_reminder(args: dict, now: datetime) -> dict:
    reminder_id = _reminder_id(args.get("id"))
    if reminder_id is None:
        return {"error": "cancel_reminder needs an integer id"}
    reminder = store.cancel(reminder_id)
    if reminder is None:
        return {"error": f"no pending reminder with id {reminder_id}"}
    return {**reminder, "status": store.CANCELLED}


_HANDLERS = {
    "web_search": _web_search,
    "add_note": _add_note,
    "add_reminder": _add_reminder,
    "list_reminders": _list_reminders,
    "cancel_reminder": _cancel_reminder,
    "list_notes": _list_notes,
}


def _spoken_time(moment: datetime) -> str:
    clock = f"{moment.hour % 12 or 12}"
    if moment.minute:
        clock += f":{moment.minute:02d}"
    return f"{clock} {'am' if moment.hour < 12 else 'pm'}"


def spoken_when(due: datetime, now: datetime) -> str:
    """'5 pm', or '10 October, 5 pm' when the due date is not today in the configured zone."""
    zone = ZoneInfo(config.TIMEZONE)
    due = due.astimezone(zone)
    when = _spoken_time(due)
    if due.date() != now.astimezone(zone).date():
        when = f"{due.day} {due.strftime('%B')}, {when}"
    return when


def reminder_text(reminder: dict, now: datetime) -> str:
    """Spoken form of a due reminder: 'Reminder, 5 pm: …' or 'Missed reminder, …' (FR-13)."""
    due = datetime.fromisoformat(reminder["due_at"])
    missed = (now - due).total_seconds() >= config.MISSED_AFTER_S
    prefix = "Missed reminder" if missed else "Reminder"
    return f"{prefix}, {spoken_when(due, now)}: {reminder['text']}"


def run(name: str, args: dict, now: datetime) -> dict:
    """Run one tool call; always returns a result dict, never raises (FR-7)."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool: {name}"}
    if not isinstance(args, dict):
        return {"error": f"{name}: arguments must be an object"}
    return handler(args, now)
