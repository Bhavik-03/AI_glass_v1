"""LLM system instruction tests (FR-6). Pure string checks: no network, no Gemini."""

from datetime import datetime
from zoneinfo import ZoneInfo

from server import config, llm


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
