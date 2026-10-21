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


@pytest.fixture(autouse=True)
def _restore_profile_state(monkeypatch):
    """The module holds the loaded profile; no test here leaks it into another file."""
    monkeypatch.setattr(profile, "_slots", [])
    monkeypatch.setattr(profile, "_values", {})


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


def _many(n: int) -> list[str]:
    return [f"s{i}" for i in range(n)]


def _load_many(monkeypatch, tmp_path, n: int, value="v") -> None:
    names = _many(n)
    _use_schema(monkeypatch, tmp_path, [_slot(x) for x in names])
    _use_values(monkeypatch, tmp_path, {x: value for x in names})
    profile.load()


def test_fr28_one_line_per_non_empty_slot_in_schema_order(monkeypatch, tmp_path):
    """render() gives one line per non-empty slot, as '<name>: <value>', in schema order."""
    _use_schema(monkeypatch, tmp_path, [_slot("b"), _slot("a"), _slot("c")])
    _use_values(monkeypatch, tmp_path, {"a": "alpha", "b": "beta", "c": "gamma"})
    profile.load()
    assert profile.render() == "b: beta\na: alpha\nc: gamma"
    assert profile.line_count() == 3


def test_fr28_empty_profile_renders_nothing(monkeypatch, tmp_path):
    """An empty profile renders nothing: empty string, zero lines."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path)
    profile.load()
    assert profile.render() == ""
    assert profile.line_count() == 0


def test_fr28_empty_and_whitespace_slots_render_nothing(monkeypatch, tmp_path):
    """A slot whose value is empty or whitespace-only renders nothing."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b"), _slot("c")])
    _use_values(monkeypatch, tmp_path, {"a": "", "b": "  \n\t", "c": "kept"})
    profile.load()
    assert profile.render() == "c: kept"


def test_fr28_half_empty_ten_slots_render_five_lines(monkeypatch, tmp_path):
    """A file with 10 slots of which half are empty renders only 5 lines."""
    _use_schema(monkeypatch, tmp_path, [_slot(x) for x in DEFAULT_NAMES])
    values = {x: ("text" if i % 2 == 0 else "") for i, x in enumerate(DEFAULT_NAMES)}
    _use_values(monkeypatch, tmp_path, values)
    profile.load()
    assert len(profile.render().split("\n")) == 5
    assert profile.line_count() == 5


def test_fr28_slot_removed_from_schema_never_renders(monkeypatch, tmp_path):
    """A slot removed from the schema never renders, even if the file still has its value."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, {"a": "kept", "ghost": "dropped"})
    profile.load()
    out = profile.render()
    assert "ghost" not in out
    assert "dropped" not in out
    assert out == "a: kept"


def test_fr28_long_value_wraps_without_losing_text(monkeypatch, tmp_path):
    """Long values wrap at PROFILE_LINE_CHARS: several lines, each <= 100 chars, no text lost."""
    words = [f"word{i}" for i in range(80)]
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, {"a": " ".join(words)})
    profile.load()
    lines = profile.render().split("\n")
    assert len(lines) > 1
    assert all(len(line) <= config.PROFILE_LINE_CHARS for line in lines)
    assert profile.line_count() == len(lines)
    assert lines[0].startswith("a: ")
    joined = " ".join(lines)[len("a: ") :].split()
    assert joined == words


def test_fr28_wrap_width_follows_config(monkeypatch, tmp_path):
    """The wrap width is config.PROFILE_LINE_CHARS, not a fixed number."""
    monkeypatch.setattr("server.config.PROFILE_LINE_CHARS", 30)
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, {"a": " ".join(["word"] * 20)})
    profile.load()
    lines = profile.render().split("\n")
    assert len(lines) > 1
    assert all(len(line) <= 30 for line in lines)


def test_fr28_41_rendered_lines_fail_load_naming_cap(monkeypatch, tmp_path):
    """A profile rendering 41 lines fails at load with a message naming the cap (40)."""
    with pytest.raises(profile.ProfileError) as exc:
        _load_many(monkeypatch, tmp_path, 41)
    assert "40" in str(exc.value)


def test_fr28_40_rendered_lines_load(monkeypatch, tmp_path):
    """A profile rendering exactly 40 lines loads."""
    _load_many(monkeypatch, tmp_path, 40)
    assert profile.line_count() == 40
    assert len(profile.render().split("\n")) == 40


def test_fr28_cap_counts_rendered_lines_not_file_lines(monkeypatch, tmp_path):
    """Fewer file lines than the cap can still go over it: 4,500 chars in one slot wrap to over 40 lines."""
    value = " ".join(["word"] * 900)
    assert len(value) >= 4000
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path, {"a": value})
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(profile.ProfileError) as exc:
        profile.load()
    assert "40" in str(exc.value)


def test_fr28_empty_slots_do_not_count_toward_cap(monkeypatch, tmp_path):
    """Empty slots render nothing, so 45 slots with 40 filled still load."""
    names = _many(45)
    _use_schema(monkeypatch, tmp_path, [_slot(x) for x in names])
    _use_values(
        monkeypatch, tmp_path, {x: ("v" if i < 40 else "") for i, x in enumerate(names)}
    )
    profile.load()
    assert profile.line_count() == 40


def test_fr28_cap_follows_config(monkeypatch, tmp_path):
    """The cap is config.PROFILE_MAX_LINES: lowered to 3, four lines fail and three load."""
    monkeypatch.setattr("server.config.PROFILE_MAX_LINES", 3)
    _load_many(monkeypatch, tmp_path, 3)
    with pytest.raises(profile.ProfileError) as exc:
        _load_many(monkeypatch, tmp_path, 4)
    assert "3" in str(exc.value)


def test_fr28_failed_load_keeps_previous_profile(monkeypatch, tmp_path):
    """A failed load leaves the previously loaded profile unchanged."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path, {"a": "good"})
    profile.load()
    before = profile.render()
    path.write_text(json.dumps({"a": " ".join(["word"] * 900)}), encoding="utf-8")
    with pytest.raises(profile.ProfileError):
        profile.load()
    assert profile.render() == before == "a: good"
    assert profile.values() == {"a": "good"}


def test_fr28_write_shows_in_values_and_render(monkeypatch, tmp_path):
    """write(slot, value) updates the held profile: values() and render() show it."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    _use_values(monkeypatch, tmp_path)
    profile.load()
    profile.write("b", "beta")
    assert profile.values() == {"b": "beta"}
    assert profile.render() == "b: beta"
    assert profile.line_count() == 1


def test_fr28_write_saves_json_to_values_file(monkeypatch, tmp_path):
    """write(slot, value) saves the value to the values file as JSON of slot to text."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    path = _use_values(monkeypatch, tmp_path, {"a": "alpha"})
    profile.load()
    profile.write("b", "beta")
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": "alpha", "b": "beta"}


def test_fr28_write_survives_reload(monkeypatch, tmp_path):
    """A write that fits survives a reload."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    _use_values(monkeypatch, tmp_path)
    profile.load()
    profile.write("a", "alpha")
    held = profile.values()
    profile.load()
    assert profile.values() == held == {"a": "alpha"}
    assert profile.render() == "a: alpha"


def test_fr28_write_overwrite_keeps_other_slots(monkeypatch, tmp_path):
    """Overwriting a slot replaces its value and keeps the other slots."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    path = _use_values(monkeypatch, tmp_path, {"a": "old", "b": "keep"})
    profile.load()
    profile.write("a", "new")
    assert profile.values() == {"a": "new", "b": "keep"}
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": "new", "b": "keep"}
    profile.load()
    assert profile.values() == {"a": "new", "b": "keep"}


def test_fr28_write_empty_string_clears_slot(monkeypatch, tmp_path):
    """A write of an empty string is allowed and clears the slot."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path, {"a": "old"})
    profile.load()
    profile.write("a", "")
    assert profile.render() == ""
    assert profile.line_count() == 0


def test_fr28_write_unknown_slot_refused_file_untouched(monkeypatch, tmp_path):
    """An unknown slot is refused; the file and the held profile are unchanged."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path, {"a": "x"})
    profile.load()
    before = path.read_bytes()
    with pytest.raises(profile.ProfileError) as exc:
        profile.write("ghost", "boo")
    assert str(exc.value).strip()
    assert path.read_bytes() == before
    assert profile.values() == {"a": "x"}


def test_fr28_write_unknown_slot_no_file_stays_missing(monkeypatch, tmp_path):
    """An unknown slot write with no values file does not create the file."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path)
    profile.load()
    with pytest.raises(profile.ProfileError):
        profile.write("ghost", "boo")
    assert not path.exists()
    assert profile.values() == {}


@pytest.mark.parametrize(
    "bad", [5, None, ["x"], b"x"], ids=["int", "none", "list", "bytes"]
)
def test_fr28_write_non_string_refused(monkeypatch, tmp_path, bad):
    """A value that is not a string is refused; nothing changes."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path, {"a": "x"})
    profile.load()
    before = path.read_bytes()
    with pytest.raises(profile.ProfileError) as exc:
        profile.write("a", bad)
    assert str(exc.value).strip()
    assert path.read_bytes() == before
    assert profile.values() == {"a": "x"}


def test_fr28_write_over_cap_refused_existing_file_unchanged(monkeypatch, tmp_path):
    """A write taking the profile over 40 lines is refused; file bytes and held profile unchanged."""
    _use_schema(monkeypatch, tmp_path, [_slot("a"), _slot("b")])
    path = _use_values(monkeypatch, tmp_path, {"a": "short"})
    profile.load()
    before_bytes = path.read_bytes()
    before_render = profile.render()
    with pytest.raises(profile.ProfileError) as exc:
        profile.write("b", " ".join(["word"] * 900))
    assert "40" in str(exc.value)
    assert path.read_bytes() == before_bytes
    assert profile.values() == {"a": "short"}
    assert profile.render() == before_render


def test_fr28_write_over_cap_refused_no_file_stays_missing(monkeypatch, tmp_path):
    """A refused over-cap write with no values file does not create one."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = _use_values(monkeypatch, tmp_path)
    profile.load()
    with pytest.raises(profile.ProfileError) as exc:
        profile.write("a", " ".join(["word"] * 900))
    assert "40" in str(exc.value)
    assert not path.exists()
    assert profile.values() == {}
    assert profile.render() == ""


def test_fr28_write_40_lines_accepted_41_refused(monkeypatch, tmp_path):
    """A write rendering exactly 40 lines is accepted; one rendering 41 is refused."""
    names = _many(41)
    _use_schema(monkeypatch, tmp_path, [_slot(x) for x in names])
    path = _use_values(monkeypatch, tmp_path)
    profile.load()
    for name in names[:40]:
        profile.write(name, "v")
    assert profile.line_count() == 40
    before = path.read_bytes()
    with pytest.raises(profile.ProfileError) as exc:
        profile.write(names[40], "v")
    assert "40" in str(exc.value)
    assert profile.line_count() == 40
    assert path.read_bytes() == before
    profile.load()
    assert profile.line_count() == 40


def test_fr28_write_one_long_slot_wrapping_over_cap_refused(monkeypatch, tmp_path):
    """One slot whose value wraps past 40 rendered lines is refused though it is a single slot."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    _use_values(monkeypatch, tmp_path)
    profile.load()
    with pytest.raises(profile.ProfileError) as exc:
        profile.write("a", " ".join(["word"] * 900))
    assert "40" in str(exc.value)
    assert profile.values() == {}


def test_fr28_write_creates_parent_folder(monkeypatch, tmp_path):
    """write creates the values file's parent folder if missing, as indented JSON."""
    _use_schema(monkeypatch, tmp_path, [_slot("a")])
    path = tmp_path / "newdir" / "sub" / "profile.json"
    monkeypatch.setattr("server.config.PROFILE_VALUES_PATH", path)
    profile.load()
    profile.write("a", "hi")
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": "hi"}
    assert "\n" in path.read_text(encoding="utf-8")
