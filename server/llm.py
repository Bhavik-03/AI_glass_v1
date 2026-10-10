import time
from datetime import datetime

from google import genai
from google.genai import types

from server import config, tools

SYSTEM_INSTRUCTION = """\
You are a voice assistant. Your answers are spoken aloud.
Now: {weekday} {day} {month_year}, {time} ({iso}), time zone {timezone}.
Home city (for weather and local questions): {home_city}.
Rules:
- Answer in at most 2 short sentences, under 40 words. Lists of notes or reminders may be longer; \
give each reminder's date and time.
- Call web_search when a question needs live information. Put the date or the home city in the \
query when the question depends on them. Never put note or reminder content in a query.
- Use the tools for notes and reminders. Turn relative times into an exact ISO 8601 time with \
offset, based on the time above.
- After any action, repeat it back with the stored values. On a tool error, say what went wrong."""

_client: genai.Client | None = None
_clock = time.monotonic


def system_instruction(now: datetime) -> str:
    """Fill the system instruction with the current time and the home city (FR-6)."""
    return SYSTEM_INSTRUCTION.format(
        weekday=now.strftime("%A"),
        day=now.day,
        month_year=now.strftime("%B %Y"),
        time=now.strftime("%H:%M"),
        iso=now.isoformat(timespec="minutes"),
        timezone=config.TIMEZONE,
        home_city=config.HOME_CITY,
    )


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=config.LLM_TIMEOUT_S * 1000),
        )
    return _client


def _check_deadline(start: float, needed_s: float) -> None:
    # A call starts only if its full timeout fits, so the stage never outlives the client's wait.
    if _clock() - start + needed_s > config.LLM_DEADLINE_S:
        raise RuntimeError("deadline exceeded")


def ask(question: str, now: datetime) -> tuple[str, bool, list[dict]]:
    """Answer one question, running Gemini's tool calls (FR-5, FR-7)."""
    tool_calls: list[dict] = []
    try:
        answer, searched = _ask(question, now, tool_calls)
    except Exception as e:
        # The caller logs the calls made before the failure (FR-17).
        e.tool_calls = tool_calls
        raise
    return answer, searched, tool_calls


def _ask(question: str, now: datetime, tool_calls: list[dict]) -> tuple[str, bool]:
    start = _clock()
    request = types.GenerateContentConfig(
        system_instruction=system_instruction(now),
        tools=[types.Tool(function_declarations=tools.DECLARATIONS)],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="VALIDATED")
        ),
        thinking_config=types.ThinkingConfig(thinking_level=config.LLM_THINKING_LEVEL),
    )
    contents = [types.Content(role="user", parts=[types.Part(text=question)])]
    searched = False
    for round_ in range(config.MAX_TOOL_ROUNDS + 1):
        _check_deadline(start, config.LLM_TIMEOUT_S)
        response = _get_client().models.generate_content(
            model=config.LLM_MODEL, contents=contents, config=request
        )
        calls = response.function_calls
        if not calls:
            return response.text, searched
        if round_ == config.MAX_TOOL_ROUNDS:
            raise RuntimeError("too many tool rounds")
        # Send the model's content back unchanged: Gemini rejects turns missing thought_signature.
        contents.append(response.candidates[0].content)
        replies = []
        for call in calls:
            if call.name == "web_search":
                _check_deadline(start, config.SEARCH_TIMEOUT_S)
            result = tools.run(call.name, call.args, now)
            searched = searched or (
                call.name == "web_search" and bool(result.get("results"))
            )
            tool_calls.append(
                {"name": call.name, "args": call.args, "ok": "error" not in result}
            )
            replies.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name, id=call.id, response=result
                    )
                )
            )
        contents.append(types.Content(role="user", parts=replies))
