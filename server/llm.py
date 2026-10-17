import json
import time
from collections.abc import Sequence
from datetime import datetime

from google import genai
from google.genai import types

from server import config, store, tools

SYSTEM_INSTRUCTION = """\
You are a voice assistant. Your answers are spoken aloud.
The user is an engineering student learning AI/ML: give an ambiguous term its AI/ML meaning \
(LoRA is the fine-tuning method, not LoRa radio).
Now: {weekday} {day} {month_year}, {time} ({iso}), time zone {timezone}.
Home city (for weather and local questions): {home_city}.
Rules:
- Answer in at most {max_sentences} sentences and at most {max_words} words.
- For a list, say the total count and the first {list_items} items (newest notes first, \
soonest reminders first); give each reminder's date and time.
- When the user says "tell me more", give the next {list_items} items or one more short \
layer, within the same limit.
- Call web_search when a question needs live information. Put the date or the home city in the \
query when the question depends on them. Never put note, reminder, concept or screen content in a query.
- Use the tools for notes and reminders. Turn relative times into an exact ISO 8601 time with \
offset, based on the time above.
- After any action, repeat it back with the stored values. On a tool error, say what went wrong.
- When you tell the user a reminder time, say the due_spoken text from the tool result, never an ISO timestamp.
- Never say an id aloud; ids are only for calling cancel_reminder.
- Call log_concept for every learning question: any factual or technical "what is X", "how does X work" or "difference between X and Y" question, in any subject, is one ("what is LoRA?"). Other questions are not ("when is Diwali?"). Reuse a listed concept name when it is the same concept.
- Call start_quiz only when the user asks to be quizzed ("quiz me"). Read the returned question exactly as given. If count is 0, say there is nothing to quiz.
Existing concept names: {concept_names}"""

GRADE_INSTRUCTION = """You grade one spoken answer to a quiz question about a concept.
The answer was transcribed by speech recognition: judge its meaning and ignore speech recognition errors, such as misheard or misspelled words.
Reply as JSON: correct is true when the answer shows the concept's meaning, otherwise false. feedback is one short line: right or wrong plus a short correction when wrong. It is spoken aloud, so use plain words."""

SKIPPED_RESULT = {
    "error": "skipped: no time left; tell the user you could not look it up, do not guess"
}

_client: genai.Client | None = None
_clock = time.monotonic


def system_instruction(now: datetime, concept_names: Sequence[str] = ()) -> str:
    """Fill the system instruction with the current time, the home city (FR-6) and the
    existing concept names, so Gemini reuses them (FR-23)."""
    return SYSTEM_INSTRUCTION.format(
        weekday=now.strftime("%A"),
        day=now.day,
        month_year=now.strftime("%B %Y"),
        time=now.strftime("%H:%M:%S"),
        iso=now.isoformat(timespec="seconds"),
        timezone=config.TIMEZONE,
        home_city=config.HOME_CITY,
        max_sentences=config.ANSWER_MAX_SENTENCES,
        max_words=config.ANSWER_MAX_WORDS,
        list_items=config.LIST_MAX_ITEMS,
        concept_names=", ".join(concept_names) or "none yet",
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


def _fits(start: float, needed_s: float, limit_s: float) -> bool:
    # A call starts only if its full timeout fits, so the stage never outlives the client's wait.
    return _clock() - start + needed_s <= limit_s


def _tool_fits(start: float, name: str) -> bool:
    """Whether a tool in a later round leaves time for the last call (FR-5)."""
    tool_s = config.SEARCH_TIMEOUT_S if name == "web_search" else 0
    return _fits(start, tool_s + config.LLM_TIMEOUT_S, config.LLM_FINAL_DEADLINE_S)


def _final_answer(
    start: float, contents: list, request: types.GenerateContentConfig, searched: bool
) -> tuple[str, bool]:
    """One last call that may not use tools, from what the tools already returned (FR-5)."""
    if _clock() - start > config.LLM_FINAL_START_MAX_S:
        raise RuntimeError("deadline exceeded")
    final = request.model_copy(
        update={
            "tool_config": types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            )
        }
    )
    try:
        response = _get_client().models.generate_content(
            model=config.LLM_MODEL, contents=contents, config=final
        )
        text = response.text
    except Exception as e:
        raise RuntimeError("deadline exceeded") from e
    if not text:
        raise RuntimeError("deadline exceeded")
    return text, searched


def ask(
    question: str,
    now: datetime,
    turns: Sequence[dict] = (),
    image: tuple[bytes, str] | None = None,
) -> tuple[str, bool, list[dict]]:
    """Answer one question after the session's earlier turns, with an optional image as
    (bytes, MIME type), running Gemini's tool calls (FR-5, FR-7, FR-20, FR-21)."""
    tool_calls: list[dict] = []
    try:
        answer, searched = _ask(question, now, turns, image, tool_calls)
    except Exception as e:
        # The caller logs the calls made before the failure (FR-17).
        e.tool_calls = tool_calls
        raise
    return answer, searched, tool_calls


def _history(turns: Sequence[dict]) -> list[types.Content]:
    """Earlier turns as user and model text, oldest first (FR-21)."""
    contents = []
    for turn in turns:
        contents.append(
            types.Content(role="user", parts=[types.Part(text=turn["question"])])
        )
        contents.append(
            types.Content(role="model", parts=[types.Part(text=turn["answer"])])
        )
    return contents


def _question(question: str, image: tuple[bytes, str] | None) -> types.Content:
    """The question as user content, with the image part first when there is one (FR-20)."""
    parts = [types.Part(text=question)]
    if image is not None:
        data, mime_type = image
        parts.insert(0, types.Part.from_bytes(data=data, mime_type=mime_type))
    return types.Content(role="user", parts=parts)


def _ask(
    question: str,
    now: datetime,
    turns: Sequence[dict],
    image: tuple[bytes, str] | None,
    tool_calls: list[dict],
) -> tuple[str, bool]:
    start = _clock()
    request = types.GenerateContentConfig(
        system_instruction=system_instruction(now, store.concept_names()),
        tools=[types.Tool(function_declarations=tools.DECLARATIONS)],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="VALIDATED")
        ),
        thinking_config=types.ThinkingConfig(thinking_level=config.LLM_THINKING_LEVEL),
    )
    contents = _history(turns) + [_question(question, image)]
    searched = False
    refused = False
    for round_ in range(config.MAX_TOOL_ROUNDS + 1):
        if refused or not _fits(start, config.LLM_TIMEOUT_S, config.LLM_DEADLINE_S):
            if round_ == 0:  # no tool has run, so there is nothing to answer from
                raise RuntimeError("deadline exceeded")
            return _final_answer(start, contents, request, searched)
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
            # The first round always runs; later ones must leave time for the last call.
            if round_ > 0 and not _tool_fits(start, call.name):
                refused = True
                result = SKIPPED_RESULT
                status = "refused"
            else:
                result = tools.run(call.name, call.args, now)
                status = "failed" if "error" in result else "ok"
            searched = searched or (
                call.name == "web_search" and bool(result.get("results"))
            )
            tool_calls.append({"name": call.name, "args": call.args, "status": status})
            replies.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name, id=call.id, response=result
                    )
                )
            )
        contents.append(types.Content(role="user", parts=replies))


def grade(name: str, summary: str, answer: str) -> dict:
    """Grade a spoken quiz answer in one Gemini call without tools; returns
    {correct, feedback} (FR-24)."""
    request = types.GenerateContentConfig(
        system_instruction=GRADE_INSTRUCTION,
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_level=config.LLM_THINKING_LEVEL),
    )
    prompt = f"Concept: {name}\nSummary: {summary}\nSpoken answer: {answer}"
    response = _get_client().models.generate_content(
        model=config.LLM_MODEL, contents=prompt, config=request
    )
    try:
        graded = json.loads(response.text)
    except (TypeError, ValueError) as e:
        raise RuntimeError("grading reply is not JSON") from e
    if not (
        isinstance(graded, dict)
        and isinstance(graded.get("correct"), bool)
        and isinstance(graded.get("feedback"), str)
        and graded["feedback"].strip()
    ):
        raise RuntimeError("grading reply lacks correct and feedback")
    return {"correct": graded["correct"], "feedback": graded["feedback"].strip()}
