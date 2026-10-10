from datetime import datetime

from server import config

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
