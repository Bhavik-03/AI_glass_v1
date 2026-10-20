from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from server import config, search, session, store

# Larger integers can't be bound as SQLite parameters (OverflowError).
SQLITE_MAX_INT = 2**63 - 1

MEMORY_TYPES = (store.FACT, store.PROJECT, store.PREFERENCE, store.SESSION)

DECLARATIONS = [
    {
        "name": "web_search",
        "description": (
            "Search the web for live or current information such as news, weather, prices "
            "or scores. The query must never contain note, reminder, concept or screen content."
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
    {
        "name": "log_concept",
        "description": (
            "Log a concept the user is learning about. Call it for learning questions only. "
            "Reuse an existing concept name when it is the same concept."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short concept name"},
                "summary": {"type": "string", "description": "One-line summary"},
            },
            "required": ["name", "summary"],
        },
    },
    {
        "name": "learned_this_week",
        "description": (
            f"Count the concepts first asked in the last {config.LEARNED_DAYS} days"
            " and name the most recent ones."
        ),
        "parameters_json_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "remember",
        "description": (
            "Remember one key point about the user, a project, a preference or a past "
            f"conversation. text is at most {config.MEMORY_MAX_WORDS} words: shorten it to "
            "the key point. Repeat the stored text back to the user; when the result has "
            "new false, say it is already remembered."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The key point"},
                "type": {
                    "type": "string",
                    "enum": list(MEMORY_TYPES),
                    "description": "fact about the user, project, preference or session summary",
                },
            },
            "required": ["text", "type"],
        },
    },
    {
        "name": "search_memories",
        "description": (
            "Look up what the user has asked to remember: facts about them, their projects "
            "and preferences, and past conversations. query is a few words about the topic; "
            "omit it to list the most recent memories. since and until narrow the search to a "
            "named time such as last week: ISO 8601, a date (2026-10-14) or a date-time with "
            "offset; a date alone means midnight in the user's time zone, and until is "
            f"exclusive. count is the total number of matches; items are the closest "
            f"{config.MEMORY_RECALL_MAX} at most, so say when count is larger. Answer only "
            "from what comes back."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A few words about the topic",
                },
                "since": {
                    "type": "string",
                    "description": "Start of the window, inclusive",
                },
                "until": {
                    "type": "string",
                    "description": "End of the window, exclusive",
                },
            },
        },
    },
    {
        "name": "forget",
        "description": (
            "Delete one memory. query is a few distinctive words from the stored text, so "
            "call search_memories first to see its exact words. It deletes only when exactly "
            "one memory contains all of the words. When it returns candidates, name them to "
            "the user and ask which; delete nothing until they answer. When it finds nothing, "
            "say so."
        ),
        "parameters_json_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Words from the memory to delete",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "start_quiz",
        "description": (
            "Start a quiz on logged concepts. Call it only when the user asks to be quizzed. "
            "Returns the first question to read out exactly, or count 0 when there is "
            "nothing to quiz."
        ),
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


def _log_concept(args: dict, now: datetime) -> dict:
    name, summary = args.get("name"), args.get("summary")
    if not isinstance(name, str) or not name.strip():
        return {"error": "log_concept needs a non-empty name"}
    if not isinstance(summary, str) or not summary.strip():
        return {"error": "log_concept needs a non-empty summary"}
    return store.log_concept(
        name.strip(), summary.strip(), now.isoformat(timespec="seconds")
    )


def _remember(args: dict, now: datetime) -> dict:
    text, kind = args.get("text"), args.get("type")
    if not isinstance(text, str) or not text.strip():
        return {"error": "remember needs a non-empty text"}
    if kind not in MEMORY_TYPES:
        return {"error": f"remember needs a type: {', '.join(MEMORY_TYPES)}"}
    try:
        return store.remember(text.strip(), kind, now.isoformat(timespec="seconds"))
    except ValueError as e:
        return {"error": f"{e}; shorten it to a key point"}


def _forget(args: dict, now: datetime) -> dict:
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return {"error": "forget needs a non-empty query"}
    result = store.forget_memory(query)
    candidates = result.get("candidates")
    if candidates is None or len(candidates) > 1:
        return result
    return {
        "error": "no memory was found containing all of those words; nothing deleted"
    }


def _search_memories(args: dict, now: datetime) -> dict:
    query = args.get("query")
    if query is not None and not isinstance(query, str):
        return {"error": "search_memories query must be text"}
    # A bound that is not text is ignored, like one the store cannot read.
    since, until = (
        v if isinstance(v, str) else None
        for v in (args.get("since"), args.get("until"))
    )
    if not query or not query.strip():
        return {
            "count": store.count_memories(since, until),
            "items": store.recent_memories(config.MEMORY_LIST_MAX, since, until),
        }
    return {
        "count": store.count_matches(query, since, until),
        "items": store.search_memories(query, config.MEMORY_RECALL_MAX, since, until),
    }


def _learned_this_week(args: dict, now: datetime) -> dict:
    since = now - timedelta(days=config.LEARNED_DAYS)
    return store.learned_since(
        since.isoformat(timespec="seconds"), config.LEARNED_MAX_NAMES
    )


def _start_quiz(args: dict, now: datetime) -> dict:
    concepts = store.quiz_concepts(config.QUIZ_MAX_CONCEPTS)
    if not concepts:
        return {"count": 0, "question": ""}
    session.start_quiz(concepts, now)
    return {"count": len(concepts), "question": quiz_question(concepts[0]["name"])}


def quiz_question(name: str) -> str:
    return config.QUIZ_QUESTION.format(name=name)


def quiz_score_text(right: int, total: int) -> str:
    return f"{right} of {total} right"


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
    "log_concept": _log_concept,
    "learned_this_week": _learned_this_week,
    "start_quiz": _start_quiz,
    "remember": _remember,
    "search_memories": _search_memories,
    "forget": _forget,
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
