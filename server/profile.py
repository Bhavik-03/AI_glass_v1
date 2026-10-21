import json
import logging
import textwrap
from datetime import date

from server import config

log = logging.getLogger(__name__)

_FIELDS = ("name", "description", "question")
# Reserved key of the values file: slot to the date it was last written (FR-30).
SET_ON_KEY = "_set_on"

_slots: list[dict] = []
_values: dict[str, str] = {}
_set_on: dict[str, date] = {}


class ProfileError(Exception):
    """The schema or the values file is unusable; the message says which and why."""


def _read_schema() -> list[dict]:
    path = config.PROFILE_SCHEMA_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ProfileError(f"profile schema {path}: cannot read: {e}") from e
    if not isinstance(raw, list):
        raise ProfileError(f"profile schema {path}: must be a list of slots")
    names: set[str] = set()
    for entry in raw:
        for field in _FIELDS:
            value = entry.get(field) if isinstance(entry, dict) else None
            if not isinstance(value, str) or not value.strip():
                raise ProfileError(
                    f"profile schema {path}: every slot needs a non-empty {field}"
                )
        if entry["name"] == SET_ON_KEY:
            raise ProfileError(
                f"profile schema {path}: {SET_ON_KEY} is a reserved name"
            )
        if entry["name"] in names:
            raise ProfileError(f"profile schema {path}: duplicate slot {entry['name']}")
        names.add(entry["name"])
    return [{field: entry[field] for field in _FIELDS} for entry in raw]


def _read_dates(raw: object, known: set[str], path) -> dict[str, date]:
    if not isinstance(raw, dict):
        raise ProfileError(
            f"profile values {path}: {SET_ON_KEY} must be an object of dates"
        )
    dates: dict[str, date] = {}
    for slot, text in raw.items():
        try:
            day = date.fromisoformat(text)
        except (TypeError, ValueError):
            day = None
        if day is None or day.isoformat() != text:
            raise ProfileError(
                f"profile values {path}: the date of {slot} in {SET_ON_KEY} "
                "must be YYYY-MM-DD"
            )
        if slot in known:
            dates[slot] = day
        else:
            log.warning(
                "profile values %s: ignoring date of unknown slot %s", path, slot
            )
    return dates


def _read_values(known: set[str]) -> tuple[dict[str, str], dict[str, date]]:
    path = config.PROFILE_VALUES_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}, {}
    except OSError as e:
        raise ProfileError(f"profile values {path}: cannot read: {e}") from e
    if not text.strip():
        return {}, {}
    try:
        raw = json.loads(text)
    except ValueError as e:
        raise ProfileError(f"profile values {path}: not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ProfileError(f"profile values {path}: must be an object of slot to text")
    dates = _read_dates(raw.pop(SET_ON_KEY), known, path) if SET_ON_KEY in raw else {}
    for slot, value in raw.items():
        if not isinstance(value, str):
            raise ProfileError(
                f"profile values {path}: the value of {slot} must be text"
            )
    for slot in raw.keys() - known:
        log.warning("profile values %s: ignoring unknown slot %s", path, slot)
    return {slot: value for slot, value in raw.items() if slot in known}, dates


def _render_lines(schema: list[dict], values: dict[str, str]) -> list[str]:
    """The lines that enter the system instruction. Wrapping at PROFILE_LINE_CHARS is
    what makes the cap a size limit: one slot is not one line however long (FR-28)."""
    lines: list[str] = []
    for slot in schema:
        value = values.get(slot["name"], "").strip()
        if value:
            lines += textwrap.wrap(
                f"{slot['name']}: {value}", width=config.PROFILE_LINE_CHARS
            )
    return lines


def _check_cap(lines: list[str]) -> None:
    if len(lines) > config.PROFILE_MAX_LINES:
        raise ProfileError(
            f"profile renders {len(lines)} lines, over the cap of "
            f"{config.PROFILE_MAX_LINES}: shorten or remove a value"
        )


def load() -> None:
    """Read the schema and the values into memory; raises ProfileError if either is
    malformed or the rendered profile is over the cap (FR-26, FR-27, FR-28)."""
    global _slots, _values, _set_on
    schema = _read_schema()
    new_values, new_dates = _read_values({slot["name"] for slot in schema})
    _check_cap(_render_lines(schema, new_values))
    _slots, _values, _set_on = schema, new_values, new_dates


def slots() -> list[dict]:
    return [dict(slot) for slot in _slots]


def values() -> dict[str, str]:
    return dict(_values)


def set_on(slot: str) -> date | None:
    """The date the slot was last written, or None when it has none (FR-30)."""
    return _set_on.get(slot)


def stale_days(today: date) -> int | None:
    """Age in days of the goal slot when it is set and more than GOAL_STALE_DAYS old;
    None otherwise, also when it has no date (FR-30)."""
    slot = config.GOAL_STALE_SLOT
    set_on_day = _set_on.get(slot)
    if set_on_day is None or not _values.get(slot, "").strip():
        return None
    age = (today - set_on_day).days
    return age if age > config.GOAL_STALE_DAYS else None


def render() -> str:
    return "\n".join(_render_lines(_slots, _values))


def line_count() -> int:
    return len(_render_lines(_slots, _values))


def write(slot: str, value: str, set_on: date) -> None:
    """Save one slot to the values file. Refused, with nothing changed, for an unknown
    slot, a value that is not text, or a profile that would render over the cap (FR-28).
    The slot's date becomes set_on, also when the value is unchanged (FR-30)."""
    global _values, _set_on
    if slot not in {s["name"] for s in _slots}:
        raise ProfileError(f"profile has no slot {slot}")
    if not isinstance(value, str):
        raise ProfileError(f"the value of {slot} must be text")
    new_values = {**_values, slot: value}
    new_dates = {**_set_on, slot: set_on}
    _check_cap(_render_lines(_slots, new_values))
    path = config.PROFILE_VALUES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(
            {
                **new_values,
                SET_ON_KEY: {k: d.isoformat() for k, d in new_dates.items()},
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    tmp.replace(path)
    _values, _set_on = new_values, new_dates
