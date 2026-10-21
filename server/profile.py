import json
import logging
import textwrap

from server import config

log = logging.getLogger(__name__)

_FIELDS = ("name", "description", "question")

_slots: list[dict] = []
_values: dict[str, str] = {}


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
        if entry["name"] in names:
            raise ProfileError(f"profile schema {path}: duplicate slot {entry['name']}")
        names.add(entry["name"])
    return [{field: entry[field] for field in _FIELDS} for entry in raw]


def _read_values(known: set[str]) -> dict[str, str]:
    path = config.PROFILE_VALUES_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as e:
        raise ProfileError(f"profile values {path}: cannot read: {e}") from e
    if not text.strip():
        return {}
    try:
        raw = json.loads(text)
    except ValueError as e:
        raise ProfileError(f"profile values {path}: not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise ProfileError(f"profile values {path}: must be an object of slot to text")
    for slot, value in raw.items():
        if not isinstance(value, str):
            raise ProfileError(
                f"profile values {path}: the value of {slot} must be text"
            )
    for slot in raw.keys() - known:
        log.warning("profile values %s: ignoring unknown slot %s", path, slot)
    return {slot: value for slot, value in raw.items() if slot in known}


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
    global _slots, _values
    schema = _read_schema()
    new_values = _read_values({slot["name"] for slot in schema})
    _check_cap(_render_lines(schema, new_values))
    _slots, _values = schema, new_values


def slots() -> list[dict]:
    return [dict(slot) for slot in _slots]


def values() -> dict[str, str]:
    return dict(_values)


def render() -> str:
    return "\n".join(_render_lines(_slots, _values))


def line_count() -> int:
    return len(_render_lines(_slots, _values))


def write(slot: str, value: str) -> None:
    """Save one slot to the values file. Refused, with nothing changed, for an unknown
    slot, a value that is not text, or a profile that would render over the cap (FR-28)."""
    global _values
    if slot not in {s["name"] for s in _slots}:
        raise ProfileError(f"profile has no slot {slot}")
    if not isinstance(value, str):
        raise ProfileError(f"the value of {slot} must be text")
    new_values = {**_values, slot: value}
    _check_cap(_render_lines(_slots, new_values))
    path = config.PROFILE_VALUES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(new_values, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    tmp.replace(path)
    _values = new_values
