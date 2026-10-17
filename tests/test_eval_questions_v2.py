"""Validates the v2 eval set eval/questions_v2.json (M12-T1; FR-19, FR-21, FR-23, FR-24)."""

import json
import re
from pathlib import Path

import pytest

QUESTIONS_PATH = Path(__file__).resolve().parent.parent / "eval" / "questions_v2.json"

GROUP_COUNTS = {"look": 20, "followup": 10, "concept": 20, "quiz": 10}
ROW_KEYS = {
    "look": {"id", "group", "spoken", "screenshot", "pass"},
    "followup": {"id", "group", "spoken", "followup", "pass"},
    "concept": {"id", "group", "spoken", "pass"},
    "quiz": {"id", "group", "spoken", "seed", "pass"},
}
ID_PREFIX = {"look": "l", "followup": "f", "concept": "c", "quiz": "q"}


@pytest.fixture(scope="module")
def data() -> dict:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(data) -> list[dict]:
    return data["rows"]


def _group(rows, name):
    return [r for r in rows if r["group"] == name]


def _nonempty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_answer_all(row):
    aa = row["pass"]["answer_all"]
    assert isinstance(aa, list) and aa, row["id"]
    for alts in aa:
        assert isinstance(alts, list) and alts, row["id"]
        for w in alts:
            assert isinstance(w, str) and w, row["id"]
            assert w == w.lower(), row["id"]


def test_fr24_top_level_shape_and_quiz_start(data):
    """File is an object with exactly quiz_start and rows; quiz_start is non-empty, no digits."""
    assert isinstance(data, dict)
    assert set(data) == {"quiz_start", "rows"}
    assert _nonempty_str(data["quiz_start"])
    assert not re.search(r"[0-9]", data["quiz_start"])


def test_fr19_sixty_rows_in_group_order(rows):
    """60 rows in group order look(20), followup(10), concept(20), quiz(10)."""
    assert isinstance(rows, list) and len(rows) == 60
    expected = [g for g, n in GROUP_COUNTS.items() for _ in range(n)]
    assert [r["group"] for r in rows] == expected


def test_fr19_ids_unique_with_group_prefix(rows):
    """Ids are unique non-empty strings with the group prefix (l01, f01, c01, q01)."""
    ids = [r["id"] for r in rows]
    assert all(isinstance(i, str) and i for i in ids)
    assert len(set(ids)) == len(ids)
    for r in rows:
        assert r["id"].startswith(ID_PREFIX[r["group"]]), r["id"]


def test_fr19_row_key_sets_exact_per_group(rows):
    """Each row has exactly the key set of its group."""
    for r in rows:
        assert set(r) == ROW_KEYS[r["group"]], r["id"]
        assert isinstance(r["pass"], dict), r["id"]


def test_fr19_spoken_non_empty_no_digits(rows):
    """Spoken text is non-empty with no digits (Whisper writes numerals)."""
    for r in rows:
        assert _nonempty_str(r["spoken"]), r["id"]
        assert not re.search(r"[0-9]", r["spoken"]), r["id"]


def test_fr19_look_screenshots_named_after_id_and_unique(rows):
    """Look rows name a unique <id>.jpg screenshot."""
    look = _group(rows, "look")
    shots = [r["screenshot"] for r in look]
    assert len(set(shots)) == len(shots)
    for r in look:
        assert isinstance(r["screenshot"], str)
        assert r["screenshot"].endswith(".jpg"), r["id"]
        assert r["screenshot"] == f"{r['id']}.jpg"


def test_fr19_look_pass_is_answer_all(rows):
    """Look pass rule is exactly answer_all with non-empty lowercase word lists."""
    for r in _group(rows, "look"):
        assert set(r["pass"]) == {"answer_all"}, r["id"]
        _check_answer_all(r)


def test_fr21_followup_second_turn_and_pass(rows):
    """Follow-up rows have a non-empty digit-free second turn and an answer_all rule."""
    for r in _group(rows, "followup"):
        assert _nonempty_str(r["followup"]), r["id"]
        assert not re.search(r"[0-9]", r["followup"]), r["id"]
        assert set(r["pass"]) == {"answer_all"}, r["id"]
        _check_answer_all(r)


def test_fr23_concept_split_ten_true_ten_false(rows):
    """Concept rows: concept_added is a bool; exactly 10 True and 10 False."""
    concept = _group(rows, "concept")
    for r in concept:
        assert set(r["pass"]) == {"concept_added"}, r["id"]
        assert isinstance(r["pass"]["concept_added"], bool), r["id"]
    flags = [r["pass"]["concept_added"] for r in concept]
    assert flags.count(True) == 10
    assert flags.count(False) == 10


def test_fr23_concept_spoken_unique(rows):
    """Concept spoken texts are unique."""
    spoken = [r["spoken"].strip().lower() for r in _group(rows, "concept")]
    assert len(set(spoken)) == len(spoken)


def test_fr24_quiz_seed_fields_and_unique_names(rows):
    """Quiz seeds have non-empty name and summary only; names unique."""
    quiz = _group(rows, "quiz")
    for r in quiz:
        seed = r["seed"]
        assert isinstance(seed, dict) and set(seed) == {"name", "summary"}, r["id"]
        assert _nonempty_str(seed["name"]), r["id"]
        assert _nonempty_str(seed["summary"]), r["id"]
    names = [r["seed"]["name"] for r in quiz]
    assert len(set(names)) == len(names)


def test_fr24_quiz_status_five_right_five_wrong(rows):
    """Quiz pass is exactly {status: right|wrong}; 5 of each."""
    quiz = _group(rows, "quiz")
    for r in quiz:
        assert set(r["pass"]) == {"status"}, r["id"]
        assert r["pass"]["status"] in ("right", "wrong"), r["id"]
    statuses = [r["pass"]["status"] for r in quiz]
    assert statuses.count("right") == 5
    assert statuses.count("wrong") == 5


def test_fr24_quiz_rows_have_no_screenshot_or_followup(rows):
    """Quiz rows carry no screenshot or followup key."""
    for r in _group(rows, "quiz"):
        assert "screenshot" not in r and "followup" not in r, r["id"]
