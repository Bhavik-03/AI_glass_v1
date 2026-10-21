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


def _use_values(monkeypatch, tmp_path, content=None):
    path = tmp_path / "profile.json"
    if content is not None:
        text = content if isinstance(content, str) else json.dumps(content)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr("server.config.PROFILE_VALUES_PATH", path)
    return path


def test_fr27_values_load_from_json_file(monkeypatch, tmp_path):
    """Values load from a JSON file of slot to text."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    _use_values(monkeypatch, tmp_path, {"a": "alpha text", "b": "beta text"})
    profile.load()
    assert profile.values() == {"a": "alpha text", "b": "beta text"}


def test_fr27_hand_edit_shows_after_reload(monkeypatch, tmp_path):
    """An edit by hand shows up after a reload."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path, {"a": "old"})
    profile.load()
    assert profile.values() == {"a": "old"}
    path.write_text(json.dumps({"a": "new"}), encoding="utf-8")
    profile.load()
    assert profile.values() == {"a": "new"}


def test_fr27_missing_file_gives_empty_profile(monkeypatch, tmp_path):
    """A missing file gives an empty profile and does not crash."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path)
    profile.load()
    assert profile.values() == {}


@pytest.mark.parametrize("content", ["", "  \n\t\n"], ids=["zero_byte", "whitespace"])
def test_fr27_empty_file_gives_empty_profile(monkeypatch, tmp_path, content):
    """An empty file gives an empty profile and does not crash."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, content)
    profile.load()
    assert profile.values() == {}


def test_fr27_unknown_slot_ignored_and_warned(monkeypatch, tmp_path, caplog):
    """A value for a slot not in the schema is ignored and logged as a warning."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, {"a": "kept", "ghost": "dropped"})
    with caplog.at_level("WARNING"):
        profile.load()
    assert profile.values() == {"a": "kept"}
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("ghost" in r.getMessage() for r in warnings)


def test_fr27_removed_schema_slot_drops_value_on_reload(monkeypatch, tmp_path, caplog):
    """A slot removed from the schema loses its value after reload (unknown, logged)."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    _use_values(monkeypatch, tmp_path, {"a": "x", "b": "y"})
    profile.load()
    assert profile.values() == {"a": "x", "b": "y"}
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    with caplog.at_level("WARNING"):
        profile.load()
    assert profile.values() == {"a": "x"}
    assert any("unknown slot b" in r.getMessage() for r in caplog.records)


def test_fr27_empty_string_slot_allowed(monkeypatch, tmp_path):
    """An empty slot is allowed."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    _use_values(monkeypatch, tmp_path, {"a": ""})
    profile.load()
    assert profile.values() == {"a": ""}


def test_fr27_values_returns_a_copy(monkeypatch, tmp_path):
    """values() returns a copy; changing it does not change the profile."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, {"a": "x"})
    profile.load()
    profile.values()["a"] = "changed"
    assert profile.values() == {"a": "x"}


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '["a", "b"]',
        '"just text"',
        '{"a": 5}',
        '{"a": ["x"]}',
        '{"a": null}',
    ],
    ids=[
        "invalid_json",
        "top_level_list",
        "top_level_string",
        "number_value",
        "list_value",
        "null_value",
    ],
)
def test_fr27_malformed_values_raise_error_naming_file(monkeypatch, tmp_path, content):
    """Invalid JSON or a value that is not text fails with a message naming the file."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, content)
    with pytest.raises(profile.ProfileError) as exc:
        profile.load()
    assert "profile.json" in str(exc.value)
