import json
import time
from collections.abc import Sequence
from datetime import datetime

from google import genai
from google.genai import types

from server import config, profile, store, tools

SYSTEM_INSTRUCTION = """\
{profile}You are a voice assistant. Your answers are spoken aloud.
The user is an engineering student learning AI/ML: give an ambiguous term its AI/ML meaning \
(LoRA is the fine-tuning method, not LoRa radio).
Now: {weekday} {day} {month_year}, {time} ({iso}), time zone {timezone}.
Home city (for weather and local questions): {home_city}.
Rules:
- Answer in at most {max_sentences} sentences and at most {max_words} words.
- For a list, say the total count and the first {list_items} items (newest notes first, \
soonest reminders first); give each reminder's date and time.
- When the user says "tell me more", continue whatever was discussed most recently: the next \
{list_items} items of a list, or one more short layer of an explanation, within the same limit. \
It is about notes only when the previous turn was about notes.
- Call web_search when a question needs live information. Put the date or the home city in the \
query when the question depends on them. Never put note, reminder, concept or screen content in a query.
- Use the tools for notes and reminders. Turn relative times into an exact ISO 8601 time with \
offset, based on the time above.
- After any action, repeat it back with the stored values. On a tool error, say what went wrong.
- When you tell the user a reminder time, say the due_spoken text from the tool result, never an ISO timestamp.
- Never say an id aloud; ids are only for calling cancel_reminder.
- Call log_concept for every learning question: any factual or technical "what is X", "how does X work" or "difference between X and Y" question, in any subject, is one ("what is LoRA?"). Other questions are not ("when is Diwali?"). Reuse a listed concept name when it is the same concept.
- Call start_quiz only when the user asks to be quizzed ("quiz me"). Read the returned question exactly as given. If count is 0, say there is nothing to quiz.
- Call remember only when the user explicitly asks you to remember something ("remember that ..."): shorten it to a key point of at most {memory_words} words, pick the type (fact, project, preference or session), and read the stored text back. If the result has new false, say it is already remembered.
- A plain statement about the user ("I have an interview next week") is not a request to remember and not a recall question: reply in one short conversational sentence, never call remember or search_memories for it, and never answer it by listing what is stored. What is worth keeping is decided after the session.
- Call search_memories for a question about something the user asked you to remember, their past projects or what you discussed before. Questions about who the user is, their goals, background or preferences are answered from the profile, not from memories. For a named time ("last week", "yesterday", "in September") pass since and until as ISO 8601 times with the offset, based on the time above; until is exclusive. For those, answer only from what comes back; if nothing does, say you do not know about that and never guess. An empty memory store never means you know nothing about the user when the profile covers it. If count is larger than the items returned, say how many there are and give the closest ones.
- To forget something, call search_memories to see its exact words, then call forget with some of those words. If forget returns candidates, name them and ask which one; delete nothing until the user answers.
- Never reuse an existing memory's wording for a different point: two things that are not the same thing are two memories.
- You cannot wipe all memories. If the user asks to delete or clear everything in any other wording ("delete all my memories", "clear everything"), tell them to say "{wipe_phrase}" exactly.
- Never put memory content in a web_search query.
- To change a profile slot, when the user asks to change one or their own words repeatedly contradict it, call propose_profile_update with the slot and the new value, then ask in one sentence for a yes, repeating the new value. You have no tool that writes a slot: a write happens only if the user says yes next. A single mention is not enough to propose. Never propose a slot the user declined.
Existing concept names: {concept_names}"""

PROFILE_HEADER = (
    "About the user. This profile is always true: answer questions about who the user is, "
    "their goals, background and preferences from it. Pitch answers to this level and "
    "weigh advice against these goals:"
)

GRADE_INSTRUCTION = """You grade one spoken answer to a quiz question about a concept.
The answer was transcribed by speech recognition: judge its meaning and ignore speech recognition errors, such as misheard or misspelled words.
Reply as JSON: correct is true when the answer shows the concept's meaning, otherwise false. feedback is one short line: right or wrong plus a short correction when wrong. It is spoken aloud, so use plain words."""

WRITER_INSTRUCTION = """{profile}You read one finished conversation between a user and a voice assistant and decide what, if anything, is worth remembering about the user.
Now: {weekday} {day} {month_year} ({iso}), time zone {timezone}.
Decide first, then word. For each candidate, first ask: would this still matter in a month? Only if it would, keep it, and only then write it as one key point of at most {memory_words} words. Never shorten a point by dropping a "not".
Keep 0 to {max_points} points, most important first. Keeping nothing is the normal result: small talk, jokes, a passing question, a general-knowledge answer, a request to be quizzed, a question restated and the assistant asking whether the month goal still holds are not worth keeping.
A dated event is not kept: "I have an interview next week" will not matter in a month. A standing fact behind it is kept: if the conversation shows that interview preparation is where the user's time is going, keep that ("preparing for interviews, most study time goes there"). Dated events belong to a planner, not to memory.
Keep only what the user said about themselves, their work, their preferences or their decisions, never something only the assistant said. Keep nothing the profile above already says.
Types: fact (about the user), project (what they are building or studying), preference (how they like things done), session (what was worked on, only when it will matter later). Two different things are two points: never reuse the wording of one point for a different point.
Reply as JSON with one key, "points": a list of objects with "text" and "type". It is an empty list when nothing is worth keeping."""

WRITER_PROFILE_HEADER = "Already known about the user (do not keep any of it again):"

SKIPPED_RESULT = {
    "error": "skipped: no time left; tell the user you could not look it up, do not guess"
}

_client: genai.Client | None = None
_clock = time.monotonic


def system_instruction(now: datetime, concept_names: Sequence[str] = ()) -> str:
    """Fill the system instruction with the current time, the home city (FR-6) and the
    existing concept names, so Gemini reuses them (FR-23)."""
    rendered = profile.render()
    return SYSTEM_INSTRUCTION.format(
        profile=f"{PROFILE_HEADER}\n{rendered}\n" if rendered else "",
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
        memory_words=config.MEMORY_MAX_WORDS,
        wipe_phrase=config.WIPE_REQUEST_PHRASE,
        concept_names=", ".join(concept_names) or "none yet",
    )


def _memories_in(name: str, result: dict) -> int:
    """How many stored memories a tool result sends to Gemini: the count only (FR-17)."""
    if name == "search_memories":
        return len(result.get("items", ()))
    if name == "forget":
        return len(result.get("candidates", ())) or int("deleted" in result)
    if name == "remember":
        # new false returns the existing stored item.
        return int(result.get("new") is False)
    return 0


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
            logged = {"name": call.name, "args": call.args, "status": status}
            if status == "ok" and (memories := _memories_in(call.name, result)):
                logged["memories"] = memories
            tool_calls.append(logged)
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


def writer_instruction(now: datetime) -> str:
    """The session writer's instruction: the profile, the clock and the salience rule (FR-28,
    FR-39). Unlike the main instruction it never carries stored memories."""
    rendered = profile.render()
    return WRITER_INSTRUCTION.format(
        profile=f"{WRITER_PROFILE_HEADER}\n{rendered}\n" if rendered else "",
        weekday=now.strftime("%A"),
        day=now.day,
        month_year=now.strftime("%B %Y"),
        iso=now.isoformat(timespec="seconds"),
        timezone=config.TIMEZONE,
        memory_words=config.MEMORY_MAX_WORDS,
        max_points=config.WRITER_MAX_POINTS,
    )


def _valid_point(point: object) -> bool:
    return (
        isinstance(point, dict)
        and isinstance(point.get("text"), str)
        and bool(point["text"].strip())
        and point.get("type") in tools.MEMORY_TYPES
    )


def write_memories(turns: Sequence[dict], now: datetime) -> list[dict]:
    """Review a finished session in one Gemini call without tools and return up to
    WRITER_MAX_POINTS key points as [{text, type}] (FR-39). The reply is only checked for
    shape: the word limit and over-merge guard are the store's."""
    request = types.GenerateContentConfig(
        system_instruction=writer_instruction(now),
        response_mime_type="application/json",
        thinking_config=types.ThinkingConfig(thinking_level=config.LLM_THINKING_LEVEL),
    )
    prompt = "\n".join(
        f"User: {turn['question']}\nAssistant: {turn['answer']}" for turn in turns
    )
    response = _get_client().models.generate_content(
        model=config.LLM_MODEL, contents=prompt, config=request
    )
    try:
        reply = json.loads(response.text)
    except (TypeError, ValueError) as e:
        raise RuntimeError("writer reply is not JSON") from e
    if not (isinstance(reply, dict) and isinstance(reply.get("points"), list)):
        raise RuntimeError("writer reply lacks a points list")  # noqa: TRY004  one error type for any unusable reply
    points = [
        {"text": p["text"].strip(), "type": p["type"]}
        for p in reply["points"]
        if _valid_point(p)
    ]
    return points[: config.WRITER_MAX_POINTS]
