"""LLM tests: system instruction (FR-6), Gemini call and tool loop (FR-5, FR-7), session turns (FR-21). Fake client, no network."""

import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from google.genai import types

from server import config, llm, tools


def fixed_now() -> datetime:
    return datetime(2026, 10, 9, 14, 0, tzinfo=ZoneInfo(config.TIMEZONE))


def test_fr6_instruction_has_date_weekday_time() -> None:
    """The instruction contains the weekday, date and time of `now`."""
    text = llm.system_instruction(fixed_now())
    assert "Friday" in text
    assert "9 October 2026" in text
    assert "14:00:00" in text


def test_fr6_instruction_has_iso_time_and_timezone() -> None:
    """The instruction contains the ISO time with offset and the time zone name."""
    text = llm.system_instruction(fixed_now())
    assert "2026-10-09T14:00:00+05:30" in text
    assert config.TIMEZONE in text


@pytest.mark.parametrize("second", [7, 59], ids=["7s", "59s"])
def test_fr6_instruction_time_includes_seconds(second: int) -> None:
    """The instruction's clock and ISO time carry the seconds of `now`, so 'in two minutes'
    lands within a few seconds of 120 s; seconds are not rounded."""
    now = datetime(2026, 10, 9, 14, 0, second, tzinfo=ZoneInfo(config.TIMEZONE))
    text = llm.system_instruction(now)
    assert f"14:00:{second:02d}" in text
    assert f"2026-10-09T14:00:{second:02d}+05:30" in text


def test_fr6_instruction_iso_time_drops_microseconds() -> None:
    """The ISO time has seconds precision: microseconds of `now` are not shown."""
    now = datetime(2026, 10, 9, 14, 0, 7, 900000, tzinfo=ZoneInfo(config.TIMEZONE))
    text = llm.system_instruction(now)
    assert "2026-10-09T14:00:07+05:30" in text
    assert "14:00:07.9" not in text


def test_fr10_instruction_says_to_repeat_due_spoken_not_iso() -> None:
    """The instruction tells Gemini to say the due_spoken text for a reminder time, never an ISO timestamp."""
    text = llm.system_instruction(fixed_now())
    assert (
        "When you tell the user a reminder time, say the due_spoken text from the "
        "tool result, never an ISO timestamp."
    ) in text


def test_fr10_instruction_says_never_to_say_ids_aloud() -> None:
    """The instruction tells Gemini never to say an id aloud; ids are only for cancel_reminder."""
    text = llm.system_instruction(fixed_now())
    assert "Never say an id aloud; ids are only for calling cancel_reminder." in text


def test_fr6_instruction_reads_home_city_per_call(monkeypatch) -> None:
    """The home city comes from config at call time, not import time."""
    monkeypatch.setattr(config, "HOME_CITY", "Testville")
    assert "Testville" in llm.system_instruction(fixed_now())


def test_fr6_instruction_has_design_rules() -> None:
    """The instruction states the web_search, ISO 8601 and repeat-back rules."""
    text = llm.system_instruction(fixed_now())
    assert "web_search" in text
    assert "ISO 8601" in text
    assert "repeat" in text.lower()


def test_fr5_instruction_limits_3_sentences_60_words() -> None:
    """The instruction says at most 3 sentences and 60 words, not the old 2 sentences / 40 words."""
    text = llm.system_instruction(fixed_now())
    assert "3 sentences" in text
    assert "60 words" in text
    assert "2 short sentences" not in text
    assert "40 words" not in text


def test_fr5_instruction_list_rule_count_and_first_5() -> None:
    """A list answer says the total count and the first 5 items (newest notes, soonest reminders)."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "total count" in text or "total number" in text
    assert "first 5" in text
    assert "newest" in text
    assert "soonest" in text


def test_fr5_instruction_tell_me_more_gives_next_5() -> None:
    """'Tell me more' gives the next 5 (or one more short layer) within the same limit."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "tell me more" in text
    assert "next 5" in text
    assert "same limit" in text


def test_fr21_instruction_tell_me_more_continues_the_last_topic() -> None:
    """'Tell me more' continues the most recent topic and means notes only after a notes turn."""
    text = " ".join(llm.system_instruction(fixed_now()).lower().split())
    assert "most recently" in text
    assert "only when the previous turn was about notes" in text


def test_fr5_instruction_numbers_follow_config(monkeypatch) -> None:
    """The limits come from config.ANSWER_MAX_SENTENCES, ANSWER_MAX_WORDS and LIST_MAX_ITEMS."""
    assert config.ANSWER_MAX_SENTENCES == 3
    assert config.ANSWER_MAX_WORDS == 60
    assert config.LIST_MAX_ITEMS == 5
    monkeypatch.setattr(config, "ANSWER_MAX_SENTENCES", 2)
    monkeypatch.setattr(config, "ANSWER_MAX_WORDS", 45)
    monkeypatch.setattr(config, "LIST_MAX_ITEMS", 4)
    text = llm.system_instruction(fixed_now())
    assert "2 sentences" in text
    assert "45 words" in text
    assert "first 4" in text
    assert "next 4" in text
    assert "3 sentences" not in text
    assert "60 words" not in text
    assert "first 5" not in text


def test_fr5_instruction_says_user_learns_ai_ml() -> None:
    """The instruction says the user is an engineering student learning AI/ML, and ambiguous terms take the AI/ML meaning."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "engineering student" in text
    assert "ai/ml" in text
    assert "ambiguous" in text


def test_fr6_instruction_has_privacy_rule() -> None:
    """The instruction says never to put note, reminder, concept or screen content in a search."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "never put note, reminder, concept or screen content in a query" in text


# --- ask(): Gemini call, tool loop, deadline (FR-5, FR-7). Fake client, no network. ---


class FakeModels:
    def __init__(self, responses: list, on_call=None) -> None:
        self.responses = list(responses)
        self.on_call = on_call
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        recorded = dict(kwargs)
        recorded["contents"] = copy.deepcopy(kwargs["contents"])
        self.calls.append(recorded)
        if self.on_call:
            self.on_call()
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list, on_call=None) -> None:
        self.models = FakeModels(responses, on_call)


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def call_response(call_id: str = "call-1") -> types.GenerateContentResponse:
    part = types.Part(
        function_call=types.FunctionCall(
            name="web_search", args={"query": "q"}, id=call_id
        ),
        thought_signature=b"sig",
    )
    content = types.Content(role="model", parts=[part])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def text_response(text: str = "answer") -> types.GenerateContentResponse:
    content = types.Content(role="model", parts=[types.Part(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


SEARCH_RESULT = {"results": [{"title": "t", "url": "u", "content": "c"}]}


def install_fake(monkeypatch, responses: list, on_call=None) -> FakeClient:
    fake = FakeClient(responses, on_call)
    monkeypatch.setattr(llm, "_client", fake)
    return fake


def install_run(monkeypatch, result: dict, on_call=None) -> list:
    seen: list = []

    def fake_run(name, args, now):
        seen.append((name, args, now))
        if on_call:
            on_call()
        return result

    monkeypatch.setattr(tools, "run", fake_run)
    return seen


def enum_value(x):
    return getattr(x, "value", x)


def test_fr5_plain_answer_request_settings(monkeypatch) -> None:
    """ask calls the configured model once with instruction, the tool declarations, VALIDATED, MINIMAL."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    now = fixed_now()
    assert llm.ask("hi", now) == ("answer", False, [])
    assert len(fake.models.calls) == 1
    call = fake.models.calls[0]
    assert call["model"] == config.LLM_MODEL
    cfg = call["config"]
    assert cfg.system_instruction == llm.system_instruction(now)
    sent = [d.name for d in cfg.tools[0].function_declarations]
    assert sent == [d["name"] for d in tools.DECLARATIONS]
    assert "web_search" in sent
    fc = cfg.tool_config.function_calling_config
    assert enum_value(fc.mode) == types.FunctionCallingConfigMode.VALIDATED.value
    assert enum_value(cfg.thinking_config.thinking_level) == "MINIMAL"
    first = call["contents"][0]
    assert first.role == "user"
    assert first.parts[0].text == "hi"


def test_fr5_client_built_once_with_key_and_timeout(monkeypatch) -> None:
    """The client is built once with the key from config and a 10 s timeout in ms."""
    built: list[dict] = []

    class Recorder:
        def __init__(self, **kwargs) -> None:
            built.append(kwargs)

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.genai, "Client", Recorder)
    first = llm._get_client()
    second = llm._get_client()
    assert first is second
    assert len(built) == 1
    assert built[0]["api_key"] == "test-key"
    assert built[0]["http_options"].timeout == config.LLM_TIMEOUT_S * 1000 == 10000


def test_fr5_empty_api_key_raises(monkeypatch) -> None:
    """An empty GEMINI_API_KEY raises and no client is constructed."""
    built: list = []
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(llm, "_client", None)
    monkeypatch.setattr(llm.genai, "Client", lambda **kw: built.append(kw))
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.ask("hi", fixed_now())
    assert built == []


def test_fr7_call_then_text_runs_tool_once(monkeypatch) -> None:
    """A function call runs tools.run once; the text answer, tool calls and searched are returned."""
    install_fake(monkeypatch, [call_response(), text_response("answer")])
    seen = install_run(monkeypatch, SEARCH_RESULT)
    now = fixed_now()
    answer, searched, tool_calls = llm.ask("q?", now)
    assert answer == "answer"
    assert seen == [("web_search", {"query": "q"}, now)]
    assert searched is True
    assert tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    ]


def test_fr7_thought_signature_round_trip(monkeypatch) -> None:
    """The second request holds the model's content with thought_signature and the function response."""
    first = call_response("call-1")
    fake = install_fake(monkeypatch, [first, text_response()])
    install_run(monkeypatch, SEARCH_RESULT)
    llm.ask("q?", fixed_now())
    assert len(fake.models.calls) == 2
    contents = fake.models.calls[1]["contents"]
    assert len(contents) == 3
    assert contents[1] == first.candidates[0].content
    part = contents[1].parts[0]
    assert part.thought_signature == b"sig"
    assert part.function_call.id == "call-1"
    reply = contents[2]
    assert reply.role == "user"
    fr = reply.parts[0].function_response
    assert fr.name == "web_search"
    assert fr.id == "call-1"
    assert fr.response == SEARCH_RESULT


def test_fr7_tool_error_marks_failed(monkeypatch) -> None:
    """A tool error gives status "failed" and searched False; the answer is still returned."""
    install_fake(monkeypatch, [call_response(), text_response("sorry")])
    install_run(monkeypatch, {"error": "x"})
    answer, searched, tool_calls = llm.ask("q?", fixed_now())
    assert answer == "sorry"
    assert searched is False
    assert tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "failed"}
    ]


def test_fr7_too_many_tool_rounds(monkeypatch) -> None:
    """More than MAX_TOOL_ROUNDS rounds raises 'too many tool rounds'."""
    rounds = config.MAX_TOOL_ROUNDS
    fake = install_fake(monkeypatch, [call_response() for _ in range(rounds + 1)])
    install_run(monkeypatch, SEARCH_RESULT)
    with pytest.raises(RuntimeError, match="too many tool rounds"):
        llm.ask("q?", fixed_now())
    assert len(fake.models.calls) == rounds + 1


def scripted_clock(monkeypatch, model_times: list[float] | None = None):
    """Install a FakeClock. After the i-th Gemini call returns, the clock reads model_times[i]
    (the last value repeats). Returns (clock, on_model_call)."""
    clock = FakeClock()
    monkeypatch.setattr(llm, "_clock", clock)
    times = list(model_times or [])
    state = {"i": 0}

    def on_model_call() -> None:
        if times:
            clock.t = times[min(state["i"], len(times) - 1)]
        state["i"] += 1

    return clock, on_model_call


def install_named_run(monkeypatch, results: dict) -> list:
    """Fake tools.run returning results[name]; records (name, args)."""
    seen: list = []

    def fake_run(name, args, now):
        seen.append((name, args))
        return results[name]

    monkeypatch.setattr(tools, "run", fake_run)
    return seen


def search_round(call_id: str):
    return named_call_response("web_search", {"query": "q"}, call_id, b"sig")


def mode_of(call: dict) -> str:
    fc = call["config"].tool_config.function_calling_config
    return enum_value(fc.mode)


def test_fr5_config_final_call_defaults() -> None:
    """LLM_FINAL_DEADLINE_S is 18 and LLM_FINAL_START_MAX_S is 8."""
    assert config.LLM_FINAL_DEADLINE_S == 18
    assert config.LLM_FINAL_START_MAX_S == 8


def test_fr5_first_round_search_runs_even_late(monkeypatch) -> None:
    """A web_search in the first tool round always runs, even when 9 s have already passed;
    the next Gemini call then does not fit and elapsed > 8, so 'deadline exceeded'."""
    _, on_model = scripted_clock(monkeypatch, [9.0])
    fake = install_fake(
        monkeypatch, [call_response(), text_response()], on_call=on_model
    )
    seen = install_run(monkeypatch, SEARCH_RESULT)
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("q?", fixed_now())
    assert len(seen) == 1
    assert exc.value.tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    ]
    assert len(fake.models.calls) == 1


def test_fr5_first_round_local_tool_runs_even_late(monkeypatch) -> None:
    """A local tool in the first tool round also runs regardless of elapsed time."""
    _, on_model = scripted_clock(monkeypatch, [9.0])
    install_fake(
        monkeypatch,
        [named_call_response("list_reminders", {}, "c1", b"s"), text_response()],
        on_call=on_model,
    )
    seen = install_named_run(monkeypatch, {"list_reminders": {"reminders": []}})
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("what reminders?", fixed_now())
    assert seen == [("list_reminders", {})]
    assert exc.value.tool_calls == [
        {"name": "list_reminders", "args": {}, "status": "ok"}
    ]


def test_fr5_deadline_before_second_gemini_call_makes_final_call(monkeypatch) -> None:
    """If the second tool-enabled call does not fit (elapsed 6 s) the FINAL call is made with
    function calling mode NONE; its text is the answer and it carries the tool results."""
    clock, _ = scripted_clock(monkeypatch)

    def advance() -> None:
        clock.t = 6.0

    fake = install_fake(monkeypatch, [call_response(), text_response("final answer")])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    answer, searched, tool_calls = llm.ask("q?", fixed_now())
    assert answer == "final answer"
    assert searched is True
    assert tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    ]
    assert len(fake.models.calls) == 2
    final = fake.models.calls[1]
    assert mode_of(final) == types.FunctionCallingConfigMode.NONE.value
    contents = final["contents"]
    assert len(contents) == 3
    assert contents[1].role == "model"
    assert contents[2].parts[0].function_response.response == SEARCH_RESULT


def test_fr5_deadline_after_late_tool_raises_without_final_call(monkeypatch) -> None:
    """At elapsed 9 s (> 8) the second call does not fit and no FINAL call is allowed:
    'deadline exceeded', no further Gemini call."""
    clock, _ = scripted_clock(monkeypatch)

    def advance() -> None:
        clock.t = 9.0

    fake = install_fake(monkeypatch, [call_response(), text_response()])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    with pytest.raises(RuntimeError, match="deadline exceeded"):
        llm.ask("q?", fixed_now())
    assert len(fake.models.calls) == 1


def test_fr5_later_round_search_refused_when_it_does_not_fit(monkeypatch) -> None:
    """A round-1 web_search at elapsed 4 s (4 + 5 + 10 > 18) is not run: it gets an error
    function response, is logged as refused, and the next request is the FINAL call."""
    clock, on_model = scripted_clock(monkeypatch)
    seen: list = []

    def fake_run(name, args, now):
        seen.append((name, args))
        clock.t = 4.0
        return SEARCH_RESULT

    monkeypatch.setattr(tools, "run", fake_run)
    fake = install_fake(
        monkeypatch,
        [search_round("c1"), search_round("c2"), text_response("no luck")],
        on_call=on_model,
    )
    answer, searched, tool_calls = llm.ask("q?", fixed_now())
    assert searched is True  # the first search returned results
    assert answer == "no luck"
    assert len(seen) == 1
    assert len(fake.models.calls) == 3
    assert tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"},
        {"name": "web_search", "args": {"query": "q"}, "status": "refused"},
    ]
    final = fake.models.calls[2]
    assert mode_of(final) == types.FunctionCallingConfigMode.NONE.value
    reply = final["contents"][4].parts[0].function_response
    assert reply.id == "c2"
    assert reply.name == "web_search"
    assert isinstance(reply.response, dict)
    assert "no time" in str(reply.response["error"])


def test_fr5_later_round_search_runs_when_it_fits(monkeypatch) -> None:
    """A round-1 web_search at elapsed 3 s (3 + 5 + 10 <= 18) runs."""
    clock, on_model = scripted_clock(monkeypatch)
    seen: list = []

    def fake_run(name, args, now):
        seen.append(name)
        clock.t = 3.0
        return SEARCH_RESULT

    monkeypatch.setattr(tools, "run", fake_run)
    fake = install_fake(
        monkeypatch,
        [search_round("c1"), search_round("c2"), text_response("done")],
        on_call=on_model,
    )
    answer, searched, tool_calls = llm.ask("q?", fixed_now())
    assert answer == "done"
    assert seen == ["web_search", "web_search"]
    assert [c["status"] for c in tool_calls] == ["ok", "ok"]
    assert searched is True
    assert (
        mode_of(fake.models.calls[2]) == types.FunctionCallingConfigMode.VALIDATED.value
    )


def test_fr7_list_then_cancel_both_run_then_text(monkeypatch) -> None:
    """list_reminders then cancel_reminder (tool timeout 0) at elapsed 3 s both run;
    the plain text answer follows and both tool calls are ok."""
    _, on_model = scripted_clock(monkeypatch, [3.0])
    fake = install_fake(
        monkeypatch,
        [
            named_call_response("list_reminders", {}, "c1", b"s1"),
            named_call_response("cancel_reminder", {"id": 4}, "c2", b"s2"),
            text_response("Cancelled."),
        ],
        on_call=on_model,
    )
    seen = install_named_run(
        monkeypatch,
        {"list_reminders": {"reminders": []}, "cancel_reminder": {"id": 4}},
    )
    answer, searched, tool_calls = llm.ask("cancel it", fixed_now())
    assert answer == "Cancelled."
    assert searched is False
    assert [s[0] for s in seen] == ["list_reminders", "cancel_reminder"]
    assert tool_calls == [
        {"name": "list_reminders", "args": {}, "status": "ok"},
        {"name": "cancel_reminder", "args": {"id": 4}, "status": "ok"},
    ]
    assert (
        mode_of(fake.models.calls[2]) == types.FunctionCallingConfigMode.VALIDATED.value
    )


def test_fr7_later_round_local_tool_runs_at_8s(monkeypatch) -> None:
    """A round-1 local tool at elapsed 8 s (8 + 0 + 10 <= 18) runs."""
    _, on_model = scripted_clock(monkeypatch, [1.0, 8.0, 8.0])
    install_fake(
        monkeypatch,
        [
            named_call_response("list_reminders", {}, "c1", b"s1"),
            named_call_response("cancel_reminder", {"id": 4}, "c2", b"s2"),
            text_response("Cancelled."),
        ],
        on_call=on_model,
    )
    seen = install_named_run(
        monkeypatch,
        {"list_reminders": {"reminders": []}, "cancel_reminder": {"id": 4}},
    )
    answer, _, tool_calls = llm.ask("cancel it", fixed_now())
    assert answer == "Cancelled."
    assert [s[0] for s in seen] == ["list_reminders", "cancel_reminder"]
    assert [c["status"] for c in tool_calls] == ["ok", "ok"]


def test_fr7_later_round_local_tool_refused_at_8_5s(monkeypatch) -> None:
    """A round-1 local tool at elapsed 8.5 s (8.5 + 10 > 18) is not run; the FINAL call is
    then not allowed (8.5 > 8), so 'deadline exceeded' with the refused call logged as refused."""
    _, on_model = scripted_clock(monkeypatch, [1.0, 8.5, 8.5])
    fake = install_fake(
        monkeypatch,
        [
            named_call_response("list_reminders", {}, "c1", b"s1"),
            named_call_response("cancel_reminder", {"id": 4}, "c2", b"s2"),
            text_response("unused"),
        ],
        on_call=on_model,
    )
    seen = install_named_run(
        monkeypatch,
        {"list_reminders": {"reminders": []}, "cancel_reminder": {"id": 4}},
    )
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("cancel it", fixed_now())
    assert [s[0] for s in seen] == ["list_reminders"]
    assert exc.value.tool_calls == [
        {"name": "list_reminders", "args": {}, "status": "ok"},
        {"name": "cancel_reminder", "args": {"id": 4}, "status": "refused"},
    ]
    assert len(fake.models.calls) == 2


@pytest.mark.parametrize(
    "bad_final",
    [
        ConnectionError("api down"),
        text_response(""),
        types.GenerateContentResponse(candidates=[]),
    ],
    ids=["api-error", "empty-text", "no-candidates"],
)
def test_fr5_final_call_failure_is_deadline_exceeded(monkeypatch, bad_final) -> None:
    """A FINAL call that raises or returns no text gives RuntimeError('deadline exceeded'),
    still carrying the tool calls made."""
    clock, _ = scripted_clock(monkeypatch)

    def advance() -> None:
        clock.t = 6.0

    fake = install_fake(monkeypatch, [call_response(), bad_final])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("q?", fixed_now())
    assert len(fake.models.calls) == 2  # the FINAL call was really made
    assert exc.value.tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    ]


def test_fr5_final_request_mode_none_normal_requests_validated(monkeypatch) -> None:
    """The FINAL request has function calling mode NONE and still declares the same tools;
    the normal requests before it keep VALIDATED."""
    clock, _ = scripted_clock(monkeypatch)

    def advance() -> None:
        clock.t = 6.0

    fake = install_fake(monkeypatch, [call_response(), text_response("x")])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    llm.ask("q?", fixed_now())
    first, final = fake.models.calls
    assert mode_of(first) == types.FunctionCallingConfigMode.VALIDATED.value
    assert mode_of(final) == types.FunctionCallingConfigMode.NONE.value
    names = [d.name for d in final["config"].tools[0].function_declarations]
    assert names == [d["name"] for d in tools.DECLARATIONS]


def test_fr7_refused_only_search_is_not_searched(monkeypatch) -> None:
    """When the only web_search is refused, then the FINAL call answers: tool_calls holds both
    calls and searched is False."""
    _, on_model = scripted_clock(monkeypatch, [1.0, 5.0, 5.0])
    fake = install_fake(
        monkeypatch,
        [
            named_call_response("list_reminders", {}, "c1", b"s1"),
            search_round("c2"),
            text_response("I could not look it up."),
        ],
        on_call=on_model,
    )
    seen = install_named_run(monkeypatch, {"list_reminders": {"reminders": []}})
    answer, searched, tool_calls = llm.ask("q?", fixed_now())
    assert answer == "I could not look it up."
    assert searched is False
    assert [s[0] for s in seen] == ["list_reminders"]
    assert tool_calls == [
        {"name": "list_reminders", "args": {}, "status": "ok"},
        {"name": "web_search", "args": {"query": "q"}, "status": "refused"},
    ]
    assert mode_of(fake.models.calls[2]) == types.FunctionCallingConfigMode.NONE.value


def test_fr17_too_many_rounds_error_carries_tool_calls(monkeypatch) -> None:
    """'too many tool rounds' is still a RuntimeError and carries the tool calls made so far."""
    rounds = config.MAX_TOOL_ROUNDS
    install_fake(monkeypatch, [call_response() for _ in range(rounds + 1)])
    install_run(monkeypatch, SEARCH_RESULT)
    with pytest.raises(RuntimeError, match="too many tool rounds") as exc:
        llm.ask("q?", fixed_now())
    expected = {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    assert exc.value.tool_calls == [expected] * rounds


def test_fr17_deadline_error_carries_tool_calls(monkeypatch) -> None:
    """'deadline exceeded' after a tool call (elapsed 9 s, no FINAL call allowed) is still a
    RuntimeError and carries that call."""
    clock = FakeClock()
    monkeypatch.setattr(llm, "_clock", clock)

    def advance() -> None:
        clock.t = 9.0

    install_fake(monkeypatch, [call_response(), text_response()])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("q?", fixed_now())
    assert exc.value.tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    ]


def test_fr17_failed_tool_call_is_recorded_on_error(monkeypatch) -> None:
    """A tool call that returned an error is carried with status "failed" when the query then fails."""
    rounds = config.MAX_TOOL_ROUNDS
    install_fake(monkeypatch, [call_response() for _ in range(rounds + 1)])
    install_run(monkeypatch, {"error": "x"})
    with pytest.raises(RuntimeError, match="too many tool rounds") as exc:
        llm.ask("q?", fixed_now())
    expected = {"name": "web_search", "args": {"query": "q"}, "status": "failed"}
    assert exc.value.tool_calls == [expected] * rounds


def test_fr17_tool_call_status_ok_has_no_ok_key(monkeypatch) -> None:
    """A tool that ran without an "error" key is recorded as exactly {"name", "args", "status": "ok"}."""
    install_fake(monkeypatch, [call_response(), text_response("answer")])
    install_run(monkeypatch, SEARCH_RESULT)
    _, _, tool_calls = llm.ask("q?", fixed_now())
    assert tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "ok"}
    ]
    assert set(tool_calls[0]) == {"name", "args", "status"}
    assert "ok" not in tool_calls[0]


def test_fr17_tool_call_status_failed_when_result_has_error(monkeypatch) -> None:
    """A tool whose result has an "error" key is recorded with status "failed" and no "ok" key."""
    install_fake(monkeypatch, [call_response(), text_response("sorry")])
    install_run(monkeypatch, {"error": "search down"})
    _, _, tool_calls = llm.ask("q?", fixed_now())
    assert tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "status": "failed"}
    ]
    assert "ok" not in tool_calls[0]


def test_fr17_tool_call_status_refused_when_skipped_for_time(monkeypatch) -> None:
    """A later-round tool skipped for lack of time (llm.SKIPPED_RESULT sent, tool not run) is
    recorded with status "refused" and no "ok" key; the earlier call that ran stays "ok"."""
    clock, on_model = scripted_clock(monkeypatch)
    seen: list = []

    def fake_run(name, args, now):
        seen.append(name)
        clock.t = 4.0
        return SEARCH_RESULT

    monkeypatch.setattr(tools, "run", fake_run)
    fake = install_fake(
        monkeypatch,
        [search_round("c1"), search_round("c2"), text_response("no luck")],
        on_call=on_model,
    )
    _, _, tool_calls = llm.ask("q?", fixed_now())
    assert seen == ["web_search"]
    assert [c["status"] for c in tool_calls] == ["ok", "refused"]
    assert all("ok" not in c for c in tool_calls)
    assert response_of(fake.models.calls[2]["contents"][4]) == llm.SKIPPED_RESULT


def test_fr17_refused_status_is_carried_on_error(monkeypatch) -> None:
    """When the query then fails ('deadline exceeded'), e.tool_calls holds the refused call
    with status "refused" and the shape {"name", "args", "status"}."""
    _, on_model = scripted_clock(monkeypatch, [1.0, 8.5, 8.5])
    install_fake(
        monkeypatch,
        [
            named_call_response("list_reminders", {}, "c1", b"s1"),
            named_call_response("cancel_reminder", {"id": 4}, "c2", b"s2"),
            text_response("unused"),
        ],
        on_call=on_model,
    )
    install_named_run(
        monkeypatch,
        {"list_reminders": {"reminders": []}, "cancel_reminder": {"id": 4}},
    )
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("cancel it", fixed_now())
    refused = exc.value.tool_calls[1]
    assert refused == {
        "name": "cancel_reminder",
        "args": {"id": 4},
        "status": "refused",
    }
    assert set(refused) == {"name", "args", "status"}


def test_fr17_first_call_failure_has_empty_tool_calls(monkeypatch) -> None:
    """A failure before any tool call propagates the same exception with tool_calls == []."""
    error = ConnectionError("boom")
    install_fake(monkeypatch, [error])
    with pytest.raises(ConnectionError, match="boom") as exc:
        llm.ask("hi", fixed_now())
    assert exc.value is error
    assert exc.value.tool_calls == []


def test_fr17_deadline_before_any_call_has_empty_tool_calls(monkeypatch) -> None:
    """'deadline exceeded' before the first Gemini call carries an empty tool_calls list."""
    monkeypatch.setattr(llm, "_clock", FakeClock())
    monkeypatch.setattr(config, "LLM_DEADLINE_S", config.LLM_TIMEOUT_S - 1)
    fake = install_fake(monkeypatch, [text_response()])
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("hi", fixed_now())
    assert exc.value.tool_calls == []
    assert fake.models.calls == []


# --- Integration: real tools + real store on a temporary DB, fake Gemini (FR-6, FR-7, FR-9, FR-10). ---

CREATED = "2026-10-09T09:00:00+05:30"
DUE_TOMORROW_5PM = "2026-10-10T17:00:00+05:30"


def named_call_response(
    name: str, args: dict, call_id: str, signature: bytes
) -> types.GenerateContentResponse:
    part = types.Part(
        function_call=types.FunctionCall(name=name, args=args, id=call_id),
        thought_signature=signature,
    )
    content = types.Content(role="model", parts=[part])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def response_of(contents_item) -> dict:
    return contents_item.parts[0].function_response.response


def test_fr6_fr9_fr10_add_reminder_stores_row_and_repeats_values(
    monkeypatch, db
) -> None:
    """'remind me tomorrow at 5 to call the lab' on 9 Oct: the stored due_at is 2026-10-10T17:00+05:30,
    the instruction carries the date context, and the stored values go back to Gemini."""
    from server import store

    args = {"text": "call the lab", "due_at": "2026-10-10T17:00:00+05:30"}
    fake = install_fake(
        monkeypatch,
        [
            named_call_response("add_reminder", args, "c1", b"sig-1"),
            text_response("Reminder set for 5 pm tomorrow: call the lab"),
        ],
    )
    result = llm.ask("remind me tomorrow at 5 to call the lab", fixed_now())

    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["due_at"] == "2026-10-10T17:00:00+05:30"
    assert pending[0]["text"] == "call the lab"

    instruction = fake.models.calls[0]["config"].system_instruction
    assert "Friday" in instruction
    assert "2026-10-09T14:00:00+05:30" in instruction

    assert len(fake.models.calls) == 2
    stored = {
        "id": pending[0]["id"],
        "text": pending[0]["text"],
        "due_at": pending[0]["due_at"],
        "due_spoken": "10 October, 5 pm",
    }
    assert response_of(fake.models.calls[1]["contents"][2]) == stored

    assert result == (
        "Reminder set for 5 pm tomorrow: call the lab",
        False,
        [{"name": "add_reminder", "args": args, "status": "ok"}],
    )


def test_fr6_fr9_add_reminder_utc_is_stored_in_kolkata_offset(monkeypatch, db) -> None:
    """A due_at sent as UTC ('...T11:30:00Z') is stored converted to Asia/Kolkata."""
    from server import store

    args = {"text": "call the lab", "due_at": "2026-10-10T11:30:00Z"}
    fake = install_fake(
        monkeypatch,
        [
            named_call_response("add_reminder", args, "c1", b"sig-1"),
            text_response("done"),
        ],
    )
    answer, _, tool_calls = llm.ask("remind me tomorrow at 5", fixed_now())

    pending = store.list_pending()
    assert len(pending) == 1
    assert pending[0]["due_at"] == DUE_TOMORROW_5PM
    assert (
        response_of(fake.models.calls[1]["contents"][2])["due_at"] == DUE_TOMORROW_5PM
    )
    assert answer == "done"
    assert tool_calls == [{"name": "add_reminder", "args": args, "status": "ok"}]


def cancel_by_description_setup(monkeypatch):
    """Two pending reminders and a model that lists, cancels the lab one, then answers."""
    from server import store

    lab = store.add_reminder("call the lab", DUE_TOMORROW_5PM, CREATED)
    other = store.add_reminder("buy milk", "2026-10-11T09:00:00+05:30", CREATED)
    first = named_call_response("list_reminders", {}, "id-list", b"signature-one")
    second = named_call_response(
        "cancel_reminder", {"id": lab["id"]}, "id-cancel", b"signature-two"
    )
    fake = install_fake(
        monkeypatch,
        [first, second, text_response("Cancelled the reminder: call the lab")],
    )
    return fake, lab, other, first, second


def test_fr9_fr10_cancel_by_description_within_round_limit(monkeypatch, db) -> None:
    """'cancel the lab reminder': list_reminders then cancel_reminder with the listed id,
    in 3 requests; only the targeted reminder is cancelled; stored values go back to Gemini."""
    from server import store

    fake, lab, other, _, _ = cancel_by_description_setup(monkeypatch)
    answer, searched, tool_calls = llm.ask("cancel the lab reminder", fixed_now())

    assert len(fake.models.calls) == 3
    assert answer == "Cancelled the reminder: call the lab"
    assert searched is False
    assert tool_calls == [
        {"name": "list_reminders", "args": {}, "status": "ok"},
        {"name": "cancel_reminder", "args": {"id": lab["id"]}, "status": "ok"},
    ]
    assert store.list_pending() == [other]

    listed = response_of(fake.models.calls[1]["contents"][2])
    assert listed == {
        "reminders": [
            {
                "id": lab["id"],
                "text": "call the lab",
                "due_at": DUE_TOMORROW_5PM,
                "due_spoken": "10 October, 5 pm",
            },
            {
                "id": other["id"],
                "text": "buy milk",
                "due_at": "2026-10-11T09:00:00+05:30",
                "due_spoken": "11 October, 9 am",
            },
        ]
    }
    cancelled = response_of(fake.models.calls[2]["contents"][4])
    assert cancelled == {
        "id": lab["id"],
        "text": "call the lab",
        "due_at": DUE_TOMORROW_5PM,
        "status": store.CANCELLED,
    }


def test_fr7_follow_up_rounds_carry_model_content_with_id_and_signature(
    monkeypatch, db
) -> None:
    """Every follow-up request carries each earlier model content unchanged (function-call id and
    thought_signature), each followed by the function response with the same id and name."""
    fake, _, _, first, second = cancel_by_description_setup(monkeypatch)
    llm.ask("cancel the lab reminder", fixed_now())

    produced = [first.candidates[0].content, second.candidates[0].content]
    calls = [c["contents"] for c in fake.models.calls]
    assert len(calls) == 3

    def check_model(item, expected, call_id, signature) -> None:
        assert item.role == expected.role == "model"
        assert item.parts == expected.parts
        assert item.parts[0].function_call.id == call_id
        assert item.parts[0].thought_signature == signature

    def check_reply(item, name, call_id) -> None:
        assert item.role == "user"
        fr = item.parts[0].function_response
        assert fr.name == name
        assert fr.id == call_id

    assert len(calls[1]) == 3
    assert calls[1][0].role == "user"
    check_model(calls[1][1], produced[0], "id-list", b"signature-one")
    check_reply(calls[1][2], "list_reminders", "id-list")

    assert len(calls[2]) == 5
    assert calls[2][0].role == "user"
    assert calls[2][0].parts[0].text == "cancel the lab reminder"
    check_model(calls[2][1], produced[0], "id-list", b"signature-one")
    check_reply(calls[2][2], "list_reminders", "id-list")
    check_model(calls[2][3], produced[1], "id-cancel", b"signature-two")
    check_reply(calls[2][4], "cancel_reminder", "id-cancel")


def test_fr7_fourth_tool_round_fails_cleanly(monkeypatch, db) -> None:
    """A conversation that needs a fourth tool round raises 'too many tool rounds' after
    MAX_TOOL_ROUNDS tool runs and MAX_TOOL_ROUNDS + 1 requests, carrying tool_calls."""
    from server import store

    assert config.MAX_TOOL_ROUNDS == 3
    rounds = config.MAX_TOOL_ROUNDS
    all_args = [
        {"text": f"task {i}", "due_at": f"2026-10-1{i}T10:00:00+05:30"}
        for i in range(6)
    ]
    responses = [
        named_call_response("add_reminder", a, f"id-{i}", f"sig-{i}".encode())
        for i, a in enumerate(all_args)
    ]
    fake = install_fake(monkeypatch, responses)

    with pytest.raises(RuntimeError, match="too many tool rounds") as exc:
        llm.ask("add many reminders", fixed_now())

    assert len(fake.models.calls) == rounds + 1
    assert len(fake.models.responses) == len(all_args) - (rounds + 1)
    assert len(store.list_pending()) == rounds
    assert exc.value.tool_calls == [
        {"name": "add_reminder", "args": a, "status": "ok"} for a in all_args[:rounds]
    ]


TURNS = [
    {"question": "q1", "answer": "a1"},
    {"question": "q2", "answer": "a2"},
]


def role_text(contents: list) -> list[tuple[str, str]]:
    return [(c.role, c.parts[0].text) for c in contents]


def test_fr21_turns_sent_before_question(monkeypatch) -> None:
    """ask sends earlier turns as user and model text, oldest first, then the new question."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("now?", fixed_now(), TURNS)
    assert role_text(fake.models.calls[0]["contents"]) == [
        ("user", "q1"),
        ("model", "a1"),
        ("user", "q2"),
        ("model", "a2"),
        ("user", "now?"),
    ]


@pytest.mark.parametrize("empty", [None, []], ids=["two-args", "empty-list"])
def test_fr21_no_turns_sends_only_question(monkeypatch, empty) -> None:
    """With no turns (2-arg call or turns=[]) contents is just the user question."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    if empty is None:
        llm.ask("hi", fixed_now())
    else:
        llm.ask("hi", fixed_now(), empty)
    assert role_text(fake.models.calls[0]["contents"]) == [("user", "hi")]


def test_fr21_turns_stay_at_start_in_tool_round(monkeypatch) -> None:
    """In a tool round the turns stay at the start of later requests, then the question,
    then the function call and response."""
    first = call_response("call-1")
    fake = install_fake(monkeypatch, [first, text_response("answer")])
    install_run(monkeypatch, SEARCH_RESULT)
    llm.ask("now?", fixed_now(), TURNS)
    assert len(fake.models.calls) == 2
    contents = fake.models.calls[1]["contents"]
    assert len(contents) == 7
    assert role_text(contents[:5]) == [
        ("user", "q1"),
        ("model", "a1"),
        ("user", "q2"),
        ("model", "a2"),
        ("user", "now?"),
    ]
    assert contents[5] == first.candidates[0].content
    assert contents[6].role == "user"
    assert contents[6].parts[0].function_response.id == "call-1"


def test_fr21_turns_list_not_mutated(monkeypatch) -> None:
    """The turns list passed to ask is not changed."""
    install_fake(monkeypatch, [text_response("answer")])
    turns = copy.deepcopy(TURNS)
    llm.ask("now?", fixed_now(), turns)
    assert turns == TURNS


JPEG_BYTES = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-bytes"


def has_inline_data(content) -> bool:
    return any(p.inline_data is not None for p in content.parts)


def test_fr20_image_part_next_to_question(monkeypatch) -> None:
    """With an image the question content is user role with an image part, then the text part."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("what is this?", fixed_now(), image=(JPEG_BYTES, "image/jpeg"))
    last = fake.models.calls[0]["contents"][-1]
    assert last.role == "user"
    assert len(last.parts) == 2
    assert last.parts[0].inline_data.data == JPEG_BYTES
    assert last.parts[0].inline_data.mime_type == "image/jpeg"
    assert last.parts[1].text == "what is this?"


def test_fr20_image_as_fourth_positional_arg(monkeypatch) -> None:
    """The image may be passed as the 4th positional argument."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("what is this?", fixed_now(), (), (JPEG_BYTES, "image/jpeg"))
    last = fake.models.calls[0]["contents"][-1]
    assert last.parts[0].inline_data.data == JPEG_BYTES
    assert last.parts[1].text == "what is this?"


def test_fr20_png_mime_type_passes_through(monkeypatch) -> None:
    """A PNG image is sent with its image/png MIME type and unchanged bytes."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("read this", fixed_now(), image=(PNG_BYTES, "image/png"))
    part = fake.models.calls[0]["contents"][-1].parts[0]
    assert part.inline_data.data == PNG_BYTES
    assert part.inline_data.mime_type == "image/png"


def test_fr20_image_only_in_question_content_with_turns(monkeypatch) -> None:
    """With turns and an image, the turns come first and are text-only; the image is only
    in the question content."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("now?", fixed_now(), TURNS, image=(JPEG_BYTES, "image/jpeg"))
    contents = fake.models.calls[0]["contents"]
    assert len(contents) == 5
    assert role_text(contents[:4]) == [
        ("user", "q1"),
        ("model", "a1"),
        ("user", "q2"),
        ("model", "a2"),
    ]
    assert all(len(c.parts) == 1 and not has_inline_data(c) for c in contents[:4])
    assert contents[4].role == "user"
    assert contents[4].parts[0].inline_data.data == JPEG_BYTES
    assert contents[4].parts[1].text == "now?"


@pytest.mark.parametrize("omit", [True, False], ids=["omitted", "none"])
def test_fr20_no_image_request_unchanged(monkeypatch, omit) -> None:
    """Without an image (omitted or None) the question content is one text part and no
    request content has inline_data."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    if omit:
        llm.ask("hi", fixed_now(), TURNS)
    else:
        llm.ask("hi", fixed_now(), TURNS, image=None)
    contents = fake.models.calls[0]["contents"]
    assert not any(has_inline_data(c) for c in contents)
    assert len(contents[-1].parts) == 1
    assert contents[-1].parts[0].text == "hi"
    assert role_text(contents)[-1] == ("user", "hi")


def test_fr20_image_stays_in_question_content_in_tool_round(monkeypatch) -> None:
    """In a tool round the image is sent once, in the question content of every request,
    and is not duplicated in the function call or response contents."""
    first = call_response("call-1")
    fake = install_fake(monkeypatch, [first, text_response("answer")])
    install_run(monkeypatch, SEARCH_RESULT)
    llm.ask("what is this?", fixed_now(), image=(JPEG_BYTES, "image/jpeg"))
    assert len(fake.models.calls) == 2
    for call in fake.models.calls:
        contents = call["contents"]
        assert contents[0].role == "user"
        assert contents[0].parts[0].inline_data.data == JPEG_BYTES
        assert contents[0].parts[1].text == "what is this?"
        assert sum(has_inline_data(c) for c in contents) == 1
    second = fake.models.calls[1]["contents"]
    assert len(second) == 3
    assert second[1] == first.candidates[0].content
    assert second[2].parts[0].function_response.id == "call-1"


@pytest.fixture(autouse=True)
def _temp_db(db) -> None:
    """ask() reads store.concept_names(): every test in this file uses the temp DB."""


def test_fr23_instruction_log_concept_for_learning_questions_only() -> None:
    """The instruction says to call log_concept for learning questions only: 'what is LoRA?'
    is one, 'when is Diwali?' is not."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "log_concept" in text
    assert "learning question" in text
    assert "what is lora?" in text
    assert "when is diwali?" in text


def test_fr23_instruction_learning_questions_cover_any_subject() -> None:
    """The log_concept rule covers factual and technical questions in any subject, not only AI/ML."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "how does x work" in text
    assert "difference between x and y" in text
    assert "any subject" in text


def test_fr23_instruction_reuses_listed_concept_name() -> None:
    """The instruction says to reuse a listed concept name for the same concept."""
    text = llm.system_instruction(fixed_now(), ["LoRA"]).lower()
    assert "reuse" in text


def test_fr5_instruction_never_puts_concepts_in_web_search_query() -> None:
    """The instruction says never to put concepts in a web_search query."""
    lines = llm.system_instruction(fixed_now()).lower().splitlines()
    assert any(
        "web_search" in line and "concept" in line and "never" in line for line in lines
    )


def test_fr23_instruction_lists_given_concept_names() -> None:
    """system_instruction lists the existing concept names it is given."""
    text = llm.system_instruction(fixed_now(), ["LoRA", "Transformers"])
    assert "LoRA" in text
    assert "Transformers" in text


def test_fr23_ask_puts_stored_concept_names_in_instruction(monkeypatch) -> None:
    """ask reads the concept names from the store on each request and the Gemini request's
    system_instruction lists them."""
    from server import store

    store.log_concept("Backpropagation", "summary", "2026-10-09T09:00:00+05:30")
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("what is it?", fixed_now())
    assert "Backpropagation" in fake.models.calls[0]["config"].system_instruction


def _quiz_rule() -> str:
    lines = llm.system_instruction(fixed_now()).lower().splitlines()
    return " ".join(line for line in lines if "start_quiz" in line)


def test_fr24_instruction_start_quiz_on_quiz_me() -> None:
    """The instruction names the start_quiz tool and the trigger phrase 'quiz me'."""
    rule = _quiz_rule()
    assert "start_quiz" in rule
    assert "quiz me" in rule


def test_fr24_instruction_start_quiz_only_when_asked() -> None:
    """The instruction says to call start_quiz only when the user asks to be quizzed."""
    rule = _quiz_rule()
    assert "only when" in rule
    assert "asks to be quizzed" in rule


def test_fr24_instruction_read_returned_question_exactly() -> None:
    """The instruction says to read the returned question exactly."""
    rule = _quiz_rule()
    assert "returned question" in rule
    assert "exactly" in rule


def test_fr24_instruction_count_zero_means_nothing_to_quiz() -> None:
    """The instruction says that when count is 0, the assistant says there is nothing to quiz."""
    rule = _quiz_rule()
    assert "count is 0" in rule
    assert "nothing to quiz" in rule


def test_fr5_api_failure_propagates(monkeypatch) -> None:
    """An exception from generate_content propagates out of ask."""
    install_fake(monkeypatch, [ConnectionError("boom")])
    with pytest.raises(ConnectionError, match="boom"):
        llm.ask("hi", fixed_now())


# --- grade(): one Gemini call that grades a spoken quiz answer (FR-24) ---


def grade_json(correct=True, feedback="Right. LoRA adds low-rank adapters.") -> str:
    return json.dumps({"correct": correct, "feedback": feedback})


def sent_text(call: dict) -> str:
    contents = call["contents"]
    if isinstance(contents, str):
        return contents
    if not isinstance(contents, list):
        contents = [contents]
    texts = []
    for item in contents:
        if isinstance(item, str):
            texts.append(item)
            continue
        texts.extend(p.text for p in item.parts if getattr(p, "text", None))
    return "\n".join(texts)


def test_fr24_grade_returns_correct_and_feedback(monkeypatch) -> None:
    """A right answer returns {"correct": True, "feedback": <Gemini's line>}."""
    install_fake(monkeypatch, [text_response(grade_json(True, "Right. Nice."))])
    result = llm.grade("LoRA", "Low-rank adapters.", "adapters")
    assert result == {"correct": True, "feedback": "Right. Nice."}


def test_fr24_grade_wrong_answer_returns_false_and_correction(monkeypatch) -> None:
    """A wrong answer returns {"correct": False, "feedback": <correction>}."""
    line = "Wrong. LoRA adds low-rank adapters."
    install_fake(monkeypatch, [text_response(grade_json(False, line))])
    result = llm.grade("LoRA", "Low-rank adapters.", "a database")
    assert result == {"correct": False, "feedback": line}


def test_fr24_grade_makes_exactly_one_call(monkeypatch) -> None:
    """grade makes exactly one Gemini call, with no tool round."""
    fake = install_fake(monkeypatch, [text_response(grade_json())])
    llm.grade("LoRA", "Low-rank adapters.", "adapters")
    assert len(fake.models.calls) == 1


def test_fr24_grade_request_has_no_tools_and_json_mime(monkeypatch) -> None:
    """The grade request carries no tools or tool_config, asks for JSON, thinking MINIMAL,
    and uses GRADE_INSTRUCTION."""
    fake = install_fake(monkeypatch, [text_response(grade_json())])
    llm.grade("LoRA", "Low-rank adapters.", "adapters")
    cfg = fake.models.calls[0]["config"]
    assert not cfg.tools
    assert cfg.tool_config is None
    assert cfg.response_mime_type == "application/json"
    assert enum_value(cfg.thinking_config.thinking_level) == "MINIMAL"
    assert cfg.system_instruction == llm.GRADE_INSTRUCTION


def test_fr24_grade_uses_configured_model(monkeypatch) -> None:
    """The grade call uses config.LLM_MODEL."""
    monkeypatch.setattr(config, "LLM_MODEL", "test-model")
    fake = install_fake(monkeypatch, [text_response(grade_json())])
    llm.grade("LoRA", "Low-rank adapters.", "adapters")
    assert fake.models.calls[0]["model"] == "test-model"


def test_fr24_grade_contents_hold_name_summary_and_answer(monkeypatch) -> None:
    """The request contents contain the concept name, its summary and the spoken answer."""
    fake = install_fake(monkeypatch, [text_response(grade_json())])
    llm.grade("Zeta-concept", "Summary about xylophones.", "my spoken guess")
    text = sent_text(fake.models.calls[0])
    assert "Zeta-concept" in text
    assert "Summary about xylophones." in text
    assert "my spoken guess" in text


def test_fr24_grade_instruction_ignores_speech_recognition_errors() -> None:
    """GRADE_INSTRUCTION says to judge the meaning and ignore speech recognition errors,
    and to give one short line of feedback with a correction."""
    text = llm.GRADE_INSTRUCTION.lower()
    assert "meaning" in text
    assert "speech recognition" in text
    assert "one" in text
    assert "correction" in text


def test_fr24_grade_client_error_propagates(monkeypatch) -> None:
    """An exception from generate_content propagates out of grade unchanged."""
    install_fake(monkeypatch, [ConnectionError("boom")])
    with pytest.raises(ConnectionError, match="boom"):
        llm.grade("LoRA", "Low-rank adapters.", "adapters")


@pytest.mark.parametrize(
    "bad",
    [
        "not json at all",
        "",
        '["correct", "feedback"]',
        '"just a string"',
        json.dumps({"feedback": "Right."}),
        json.dumps({"correct": True}),
        json.dumps({"correct": "yes", "feedback": "Right."}),
        json.dumps({"correct": 1, "feedback": "Right."}),
        json.dumps({"correct": None, "feedback": "Right."}),
        json.dumps({"correct": True, "feedback": ""}),
        json.dumps({"correct": True, "feedback": "   "}),
    ],
    ids=[
        "bad-json",
        "empty-text",
        "list",
        "string",
        "missing-correct",
        "missing-feedback",
        "correct-str",
        "correct-int",
        "correct-null",
        "feedback-empty",
        "feedback-blank",
    ],
)
def test_fr24_grade_unreadable_response_raises(monkeypatch, bad: str) -> None:
    """Text that is not a JSON object with a bool `correct` and a non-empty `feedback` raises."""
    install_fake(monkeypatch, [text_response(bad)])
    with pytest.raises(RuntimeError):
        llm.grade("LoRA", "Low-rank adapters.", "adapters")


def test_fr33_instruction_remember_key_point_word_limit(monkeypatch) -> None:
    """The instruction tells Gemini to call remember and shorten to a key point within the configured word limit."""
    monkeypatch.setattr(config, "MEMORY_MAX_WORDS", 7)
    text = llm.system_instruction(fixed_now()).lower()
    assert "remember" in text
    assert "key point" in text
    assert "7 words" in text


def test_fr33_instruction_lists_memory_types() -> None:
    """The instruction tells Gemini to pick the type: fact, project, preference or session."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "fact, project, preference or session" in text


def test_fr33_instruction_reads_back_stored_text() -> None:
    """The instruction tells Gemini to read the stored text back."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "read the stored text back" in text


def test_fr33_instruction_already_remembered_when_not_new() -> None:
    """The instruction says to say it is already remembered when new is false."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "new false" in text
    assert "already remembered" in text


def test_fr37_instruction_search_memories_for_user_questions() -> None:
    """The instruction names search_memories for questions about the user or earlier conversations."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "search_memories" in text
    assert "about the user" in text
    assert "discussed before" in text


def test_fr37_instruction_since_until_iso_with_offset() -> None:
    """The instruction says to pass since and until as ISO 8601 with offset for a named time, until exclusive."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "since and until" in text
    assert "iso 8601" in text
    assert "offset" in text
    assert "until is exclusive" in text


def test_fr37_instruction_answer_only_from_results() -> None:
    """The instruction says to answer only from what comes back and say it does not know when nothing does."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "answer only from what comes back" in text
    assert "do not know" in text
    assert "never guess" in text


def test_fr38_instruction_says_how_many_when_count_larger() -> None:
    """The instruction says to say how many there are when count is larger than the items returned."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "count is larger than the items returned" in text
    assert "say how many" in text


def test_fr34_instruction_forget_searches_first_then_forgets() -> None:
    """The instruction says to search_memories first, then call forget with some of the item's words."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "to forget" in text
    assert "call search_memories to see its exact words" in text
    assert "call forget with some of those words" in text


def test_fr34_instruction_forget_candidates_ask_which() -> None:
    """The instruction says to name the candidates, ask which one, and delete nothing until the user answers."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "candidates" in text
    assert "ask which" in text
    assert "delete nothing until the user answers" in text


def test_fr33_instruction_never_reuse_memory_wording() -> None:
    """The instruction says never to reuse an existing memory's wording for a different point."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "never reuse an existing memory's wording for a different point" in text


def test_fr35_instruction_cannot_wipe_says_exact_phrase(monkeypatch) -> None:
    """The instruction says Gemini cannot wipe and to tell the user to say the configured phrase exactly."""
    monkeypatch.setattr(config, "WIPE_REQUEST_PHRASE", "erase the whole memory bank")
    text = llm.system_instruction(fixed_now()).lower()
    assert "cannot wipe" in text
    assert "erase the whole memory bank" in text
    assert "exactly" in text


def test_fr35_instruction_mentions_other_wipe_wordings() -> None:
    """The instruction covers other wordings such as 'delete all my memories' and 'clear everything'."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "delete" in text
    assert "clear" in text
    assert "in any other wording" in text


def test_fr33_instruction_forbids_memory_content_in_web_search() -> None:
    """The instruction says never to put memory content in a web_search query."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "never put memory content in a web_search query" in text


def test_fr33_instruction_still_formats_and_keeps_earlier_rules() -> None:
    """The instruction formats without KeyError and keeps the note/reminder/concept/screen rule."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "never put note, reminder, concept or screen content in a query" in text


def test_fr35_instruction_names_the_other_wipe_wordings():
    """The instruction gives "delete all my memories" and "clear everything" as the wordings to redirect."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "delete all my memories" in text
    assert "clear everything" in text


# --- memories count on tool calls (FR-37, FR-17). Real store on the temp DB, fake Gemini. ---


def _store_annotation_notes(n: int) -> None:
    from server import store

    for i in range(n):
        store.add_memory(
            f"annotation note number {i}", store.FACT, "2026-10-09T10:00:00+05:30"
        )


def _one_call_then_text(monkeypatch, name: str, args: dict):
    return install_fake(
        monkeypatch,
        [named_call_response(name, args, "c1", b"s1"), text_response("done")],
    )


def test_fr37_recall_with_50_memories_sends_at_most_5_items(monkeypatch) -> None:
    """With 50 memories stored, the recall question's function response carries at most 5 items
    and the count of all matches."""
    _store_annotation_notes(50)
    fake = _one_call_then_text(monkeypatch, "search_memories", {"query": "annotation"})
    llm.ask("what do I know about annotation?", fixed_now())
    sent = response_of(fake.models.calls[1]["contents"][2])
    assert len(sent["items"]) == 5
    assert sent["count"] == 50


def test_fr37_recall_log_entry_counts_5_memories(monkeypatch) -> None:
    """The ok search_memories call carries "memories": 5, the number of items sent to Gemini."""
    _store_annotation_notes(50)
    args = {"query": "annotation"}
    _one_call_then_text(monkeypatch, "search_memories", args)
    _, _, tool_calls = llm.ask("what do I know about annotation?", fixed_now())
    assert tool_calls == [
        {"name": "search_memories", "args": args, "status": "ok", "memories": 5}
    ]


def test_fr37_search_with_no_match_has_no_memories_key(monkeypatch) -> None:
    """A search with zero items sends no memory text, so the call has no "memories" key."""
    _store_annotation_notes(3)
    _one_call_then_text(monkeypatch, "search_memories", {"query": "quantum"})
    _, _, tool_calls = llm.ask("what about quantum?", fixed_now())
    assert tool_calls[0]["status"] == "ok"
    assert "memories" not in tool_calls[0]


def test_fr37_list_mode_without_query_counts_the_5_listed(monkeypatch) -> None:
    """A search with no query on 8 stored memories lists 5 and counts "memories": 5."""
    _store_annotation_notes(8)
    fake = _one_call_then_text(monkeypatch, "search_memories", {})
    _, _, tool_calls = llm.ask("list my memories", fixed_now())
    sent = response_of(fake.models.calls[1]["contents"][2])
    assert len(sent["items"]) == 5
    assert sent["count"] == 8
    assert tool_calls[0]["memories"] == 5


def test_fr37_remember_new_has_no_memories_key(monkeypatch) -> None:
    """A remember that stores a new item (new True) sends no stored memory text: no "memories" key."""
    _one_call_then_text(
        monkeypatch,
        "remember",
        {"text": "Studying LoRA fine-tuning", "type": "fact"},
    )
    _, _, tool_calls = llm.ask("remember that I study LoRA", fixed_now())
    assert tool_calls[0]["status"] == "ok"
    assert "memories" not in tool_calls[0]


def test_fr37_remember_repeat_counts_one_memory(monkeypatch) -> None:
    """A near-verbatim repeat (new False) returns the existing stored item: "memories": 1."""
    from server import store

    store.add_memory(
        "Studying LoRA fine-tuning", store.FACT, "2026-10-09T10:00:00+05:30"
    )
    _one_call_then_text(
        monkeypatch,
        "remember",
        {"text": "I am studying LoRA fine tuning", "type": "fact"},
    )
    _, _, tool_calls = llm.ask("remember that I study LoRA", fixed_now())
    assert tool_calls[0]["status"] == "ok"
    assert tool_calls[0]["memories"] == 1


def test_fr37_forget_ambiguous_counts_candidates_and_deletes_nothing(
    monkeypatch,
) -> None:
    """A forget returning 2 candidates counts "memories": 2 and deletes nothing."""
    from server import store

    store.add_memory("Gym session on Monday", store.FACT, "2026-10-09T10:00:00+05:30")
    store.add_memory("Gym session on Friday", store.FACT, "2026-10-09T10:00:00+05:30")
    _one_call_then_text(monkeypatch, "forget", {"query": "gym session"})
    _, _, tool_calls = llm.ask("forget my gym session", fixed_now())
    assert tool_calls[0]["memories"] == 2
    assert store.count_memories() == 2


def test_fr37_forget_single_match_counts_one(monkeypatch) -> None:
    """A forget that deletes its one match returned that item to Gemini: "memories": 1."""
    from server import store

    store.add_memory("Gym on Monday", store.FACT, "2026-10-09T10:00:00+05:30")
    _one_call_then_text(monkeypatch, "forget", {"query": "gym Monday"})
    _, _, tool_calls = llm.ask("forget my gym day", fixed_now())
    assert tool_calls[0]["status"] == "ok"
    assert tool_calls[0]["memories"] == 1
    assert store.count_memories() == 0


def test_fr37_failed_call_has_no_memories_key(monkeypatch) -> None:
    """A failed call (search_memories with a non-string query) has no "memories" key."""
    _store_annotation_notes(3)
    _one_call_then_text(monkeypatch, "search_memories", {"query": 5})
    _, _, tool_calls = llm.ask("what do I know?", fixed_now())
    assert tool_calls[0]["status"] == "failed"
    assert "memories" not in tool_calls[0]


def test_fr37_refused_call_has_no_memories_key(monkeypatch) -> None:
    """A search_memories call refused for lack of time has no "memories" key."""
    _store_annotation_notes(3)
    _, on_model = scripted_clock(monkeypatch, [1.0, 8.5, 8.5])
    install_fake(
        monkeypatch,
        [
            named_call_response("list_reminders", {}, "c1", b"s1"),
            named_call_response(
                "search_memories", {"query": "annotation"}, "c2", b"s2"
            ),
            text_response("unused"),
        ],
        on_call=on_model,
    )
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("what do I know?", fixed_now())
    assert exc.value.tool_calls[1]["status"] == "refused"
    assert "memories" not in exc.value.tool_calls[1]


def test_fr37_two_searches_are_counted_on_their_own_entries(monkeypatch) -> None:
    """Two search_memories calls in one answer each carry their own count."""
    from server import store

    for i in range(3):
        store.add_memory(f"alpha topic {i}", store.FACT, "2026-10-09T10:00:00+05:30")
    for i in range(2):
        store.add_memory(f"beta topic {i}", store.FACT, "2026-10-09T10:00:00+05:30")
    install_fake(
        monkeypatch,
        [
            named_call_response("search_memories", {"query": "alpha"}, "c1", b"s1"),
            named_call_response("search_memories", {"query": "beta"}, "c2", b"s2"),
            text_response("done"),
        ],
    )
    _, _, tool_calls = llm.ask("compare alpha and beta", fixed_now())
    assert [c["memories"] for c in tool_calls] == [3, 2]


def test_fr37_store_is_never_sent_with_the_first_request(monkeypatch) -> None:
    """With 50 memories stored, no memory text is in the system instruction or the first
    request's text parts; only the instruction and the question are sent."""
    _store_annotation_notes(50)
    fake = install_fake(monkeypatch, [text_response("answer")])
    llm.ask("what is the weather?", fixed_now())
    call = fake.models.calls[0]
    assert sent_text(call) == "what is the weather?"
    assert "annotation note number" not in call["config"].system_instruction
