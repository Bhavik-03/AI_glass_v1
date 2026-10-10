"""LLM tests: system instruction (FR-6), Gemini call and tool loop (FR-5, FR-7). Fake client, no network."""

import copy
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
    assert "14:00" in text


def test_fr6_instruction_has_iso_time_and_timezone() -> None:
    """The instruction contains the ISO time with offset and the time zone name."""
    text = llm.system_instruction(fixed_now())
    assert "2026-10-09T14:00+05:30" in text
    assert config.TIMEZONE in text


def test_fr6_instruction_reads_home_city_per_call(monkeypatch) -> None:
    """The home city comes from config at call time, not import time."""
    monkeypatch.setattr(config, "HOME_CITY", "Testville")
    assert "Testville" in llm.system_instruction(fixed_now())


def test_fr6_instruction_has_design_rules() -> None:
    """The instruction states the length, web_search, ISO 8601 and repeat-back rules."""
    text = llm.system_instruction(fixed_now())
    assert "40 words" in text
    assert "web_search" in text
    assert "ISO 8601" in text
    assert "repeat" in text.lower()


def test_fr6_instruction_has_privacy_rule() -> None:
    """The instruction says never to put note or reminder content in a search."""
    text = llm.system_instruction(fixed_now()).lower()
    assert "never put note or reminder content in a query" in text


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
    """ask calls the configured model once with instruction, web_search, VALIDATED, MINIMAL."""
    fake = install_fake(monkeypatch, [text_response("answer")])
    now = fixed_now()
    assert llm.ask("hi", now) == ("answer", False, [])
    assert len(fake.models.calls) == 1
    call = fake.models.calls[0]
    assert call["model"] == config.LLM_MODEL
    cfg = call["config"]
    assert cfg.system_instruction == llm.system_instruction(now)
    assert [d.name for d in cfg.tools[0].function_declarations] == ["web_search"]
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
    assert tool_calls == [{"name": "web_search", "args": {"query": "q"}, "ok": True}]


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


def test_fr7_tool_error_marks_not_ok(monkeypatch) -> None:
    """A tool error gives ok False and searched False; the answer is still returned."""
    install_fake(monkeypatch, [call_response(), text_response("sorry")])
    install_run(monkeypatch, {"error": "x"})
    answer, searched, tool_calls = llm.ask("q?", fixed_now())
    assert answer == "sorry"
    assert searched is False
    assert tool_calls == [{"name": "web_search", "args": {"query": "q"}, "ok": False}]


def test_fr7_too_many_tool_rounds(monkeypatch) -> None:
    """More than MAX_TOOL_ROUNDS rounds raises 'too many tool rounds'."""
    rounds = config.MAX_TOOL_ROUNDS
    fake = install_fake(monkeypatch, [call_response() for _ in range(rounds + 1)])
    install_run(monkeypatch, SEARCH_RESULT)
    with pytest.raises(RuntimeError, match="too many tool rounds"):
        llm.ask("q?", fixed_now())
    assert len(fake.models.calls) == rounds + 1


def test_fr5_deadline_before_search(monkeypatch) -> None:
    """A search whose 5 s timeout does not fit in the 15 s deadline raises 'deadline exceeded'."""
    clock = FakeClock()
    monkeypatch.setattr(llm, "_clock", clock)

    def advance() -> None:
        clock.t = 12.0

    install_fake(monkeypatch, [call_response(), text_response()], on_call=advance)
    seen = install_run(monkeypatch, SEARCH_RESULT)
    with pytest.raises(RuntimeError, match="deadline exceeded"):
        llm.ask("q?", fixed_now())
    assert seen == []


def test_fr5_deadline_before_second_gemini_call(monkeypatch) -> None:
    """A Gemini call whose 10 s timeout does not fit in the time left raises 'deadline exceeded'."""
    clock = FakeClock()
    monkeypatch.setattr(llm, "_clock", clock)

    def advance() -> None:
        clock.t = 6.0

    fake = install_fake(monkeypatch, [call_response(), text_response()])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    with pytest.raises(RuntimeError, match="deadline exceeded"):
        llm.ask("q?", fixed_now())
    assert len(fake.models.calls) == 1


def test_fr17_too_many_rounds_error_carries_tool_calls(monkeypatch) -> None:
    """'too many tool rounds' is still a RuntimeError and carries the tool calls made so far."""
    rounds = config.MAX_TOOL_ROUNDS
    install_fake(monkeypatch, [call_response() for _ in range(rounds + 1)])
    install_run(monkeypatch, SEARCH_RESULT)
    with pytest.raises(RuntimeError, match="too many tool rounds") as exc:
        llm.ask("q?", fixed_now())
    expected = {"name": "web_search", "args": {"query": "q"}, "ok": True}
    assert exc.value.tool_calls == [expected] * rounds


def test_fr17_deadline_error_carries_tool_calls(monkeypatch) -> None:
    """'deadline exceeded' after a tool call is still a RuntimeError and carries that call."""
    clock = FakeClock()
    monkeypatch.setattr(llm, "_clock", clock)

    def advance() -> None:
        clock.t = 6.0

    install_fake(monkeypatch, [call_response(), text_response()])
    install_run(monkeypatch, SEARCH_RESULT, on_call=advance)
    with pytest.raises(RuntimeError, match="deadline exceeded") as exc:
        llm.ask("q?", fixed_now())
    assert exc.value.tool_calls == [
        {"name": "web_search", "args": {"query": "q"}, "ok": True}
    ]


def test_fr17_failed_tool_call_is_recorded_on_error(monkeypatch) -> None:
    """A tool call that returned an error is carried with ok False when the query then fails."""
    rounds = config.MAX_TOOL_ROUNDS
    install_fake(monkeypatch, [call_response() for _ in range(rounds + 1)])
    install_run(monkeypatch, {"error": "x"})
    with pytest.raises(RuntimeError, match="too many tool rounds") as exc:
        llm.ask("q?", fixed_now())
    expected = {"name": "web_search", "args": {"query": "q"}, "ok": False}
    assert exc.value.tool_calls == [expected] * rounds


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


def test_fr5_api_failure_propagates(monkeypatch) -> None:
    """An exception from generate_content propagates out of ask."""
    install_fake(monkeypatch, [ConnectionError("boom")])
    with pytest.raises(ConnectionError, match="boom"):
        llm.ask("hi", fixed_now())
