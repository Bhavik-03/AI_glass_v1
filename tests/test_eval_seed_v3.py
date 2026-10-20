"""Validates the v3 eval seed eval/seed_v3.json (M14-T1; FR-37)."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from eval import config as eval_config
from server import config, store

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
KEYS = {"text", "type", "created_at"}
TYPES = {store.FACT, store.PROJECT, store.PREFERENCE, store.SESSION}
OFFSET = timedelta(hours=5, minutes=30)


@pytest.fixture(scope="module")
def items() -> list[dict]:
    return json.loads(eval_config.V3_SEED_PATH.read_text(encoding="utf-8"))


def test_fr37_seed_path_is_inside_eval_folder_not_the_database():
    """The seed is the eval's own file in eval/, never data/assistant.db or anything in data/."""
    path = Path(eval_config.V3_SEED_PATH).resolve()
    assert path == EVAL_DIR / "seed_v3.json"
    assert path.is_file()
    assert path != Path(config.DB_PATH).resolve()
    assert (ROOT / "data") not in path.parents


def test_fr37_seed_is_forty_objects_with_exact_keys(items):
    """The file is a list of about 40 objects with exactly text, type, created_at (non-empty strings)."""
    assert isinstance(items, list) and len(items) == 40
    for item in items:
        assert isinstance(item, dict) and set(item) == KEYS, item
        for key in KEYS:
            assert isinstance(item[key], str) and item[key].strip(), item


def test_fr37_all_four_types_appear_and_none_other(items):
    """Every type is fact, project, preference or session, and all four appear."""
    types = {i["type"] for i in items}
    assert types <= TYPES
    assert types == TYPES


def test_fr37_each_text_within_memory_max_words(items):
    """Each item has at most MEMORY_MAX_WORDS words."""
    for item in items:
        assert len(item["text"].split()) <= config.MEMORY_MAX_WORDS, item["text"]


def test_fr37_texts_are_unique_case_insensitively(items):
    """No two items share the same text, ignoring case."""
    texts = [i["text"].strip().lower() for i in items]
    assert len(set(texts)) == len(texts)


def test_fr37_created_at_has_ist_offset(items):
    """Every created_at parses as ISO 8601 and carries the +05:30 offset."""
    for item in items:
        stamp = datetime.fromisoformat(item["created_at"])
        assert stamp.utcoffset() == OFFSET, item["created_at"]


def test_fr37_created_at_spread_is_about_twelve_weeks(items):
    """Earliest to latest created_at spans 70 to 91 days, and dates are not all the same."""
    stamps = [datetime.fromisoformat(i["created_at"]) for i in items]
    assert len(set(stamps)) > 1
    spread = max(stamps) - min(stamps)
    assert timedelta(days=70) <= spread <= timedelta(days=91)


def test_fr37_every_item_loads_as_a_new_row(db, items):
    """Loading the seed in file order through store.remember makes 40 new rows; none collapse under find_same."""
    for item in items:
        result = store.remember(item["text"], item["type"], item["created_at"])
        assert result["new"] is True, item["text"]
    with sqlite3.connect(db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    assert count == 40
