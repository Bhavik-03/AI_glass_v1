"""Tests for server/profile.py: schema, values, render and cap (FR-26, FR-27, FR-28)."""

import json

import pytest

from server import config, profile

DEFAULT_NAMES = [
    "identity",
    "goal_now",
    "goal_mid",
    "goal_long",
    "interests",
    "exploring",
    "understanding",
    "skillset",
    "style",
    "constraints",
]


def _slot(name: str) -> dict:
    return {"name": name, "description": f"{name} desc", "question": f"{name}?"}


def _use_schema(monkeypatch, tmp_path, content) -> None:
    path = tmp_path / "schema.json"
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr("server.config.PROFILE_SCHEMA_PATH", path)


def test_fr26_config_values():
    assert config.PROFILE_SCHEMA_PATH == config.ROOT / "config" / "profile_schema.json"
    assert config.PROFILE_VALUES_PATH == config.ROOT / "data" / "profile.json"
    assert config.PROFILE_MAX_LINES == 40
    assert config.PROFILE_LINE_CHARS == 100


def test_fr26_default_schema_has_ten_slots_in_order():
    assert config.PROFILE_SCHEMA_PATH == config.ROOT / "config" / "profile_schema.json"
    profile.load()
    slots = profile.slots()
    assert [s["name"] for s in slots] == DEFAULT_NAMES
    for s in slots:
        assert s["description"].strip()
        assert s["question"].strip()


def test_fr26_slots_come_from_file_and_keep_order(monkeypatch, tmp_path):
    _use_schema(monkeypatch, tmp_path, [_slot("zeta"), _slot("alpha")])
    profile.load()
    assert [s["name"] for s in profile.slots()] == ["zeta", "alpha"]
    assert profile.slots()[0] == _slot("zeta")


def test_fr26_added_slot_known_after_reload(monkeypatch, tmp_path):
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    profile.load()
    assert [s["name"] for s in profile.slots()] == ["a"]
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    profile.load()
    assert [s["name"] for s in profile.slots()] == ["a", "b"]


def test_fr26_removed_slot_gone_after_reload(monkeypatch, tmp_path):
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    profile.load()
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    profile.load()
    assert [s["name"] for s in profile.slots()] == ["a"]


@pytest.mark.parametrize(
    ("content", "mention"),
    [
        ("{not json", "schema.json"),
        ({"name": "x"}, "schema.json"),
        ([{"name": "x", "description": "d"}], "question"),
        ([{"name": "x", "question": "q"}], "description"),
        ([{"description": "d", "question": "q"}], "name"),
        ([_slot("")], "name"),
        ([_slot("dup"), _slot("dup")], "dup"),
    ],
    ids=[
        "invalid_json",
        "top_level_not_list",
        "missing_question",
        "missing_description",
        "missing_name",
        "empty_name",
        "duplicate_name",
    ],
)
def test_fr26_malformed_schema_raises_clear_error(
    monkeypatch, tmp_path, content, mention
):
    _use_schema(monkeypatch, tmp_path, content)
    with pytest.raises(profile.ProfileError) as exc:
        profile.load()
    message = str(exc.value)
    assert message.strip()
    assert mention in message
