import json
import logging

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


def load() -> None:
    """Read the schema and the values into memory; raises ProfileError if either is
    malformed (FR-26, FR-27)."""
    global _slots, _values
    schema = _read_schema()
    _values = _read_values({slot["name"] for slot in schema})
    _slots = schema


def slots() -> list[dict]:
    return [dict(slot) for slot in _slots]


def values() -> dict[str, str]:
    return dict(_values)
