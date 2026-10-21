import json

from server import config

_FIELDS = ("name", "description", "question")

_slots: list[dict] = []


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


def load() -> None:
    """Read the schema into memory; raises ProfileError if it is malformed (FR-26)."""
    global _slots
    _slots = _read_schema()


def slots() -> list[dict]:
    return [dict(slot) for slot in _slots]
