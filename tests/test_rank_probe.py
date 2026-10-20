"""Tests for the ranking probe eval/rank_probe.py (M14-T2; FR-37)."""

import json

import pytest

from eval import config as eval_config
from eval import rank_probe
from server import config, store

REAL_DB = config.DB_PATH
IST = "+05:30"


def item(text: str, day: int = 1, kind: str = store.FACT) -> dict:
    return {
        "text": text,
        "type": kind,
        "created_at": f"2026-08-{day:02d}T09:00:00{IST}",
    }


TINY_ITEMS = [
    item("Bhavik studies linear algebra every morning", 1),
    item("Prefers dark mode in the editor", 2, store.PREFERENCE),
    item("Project uses a FastAPI backend", 3, store.PROJECT),
]


def content_stems(text: str) -> set[str]:
    return {store._stem(w) for w in store._words(text) if w not in store.STOPWORDS}


def real_seed() -> list[dict]:
    return json.loads(eval_config.V3_SEED_PATH.read_text(encoding="utf-8"))


def real_db_state():
    return REAL_DB.stat().st_mtime_ns if REAL_DB.exists() else None


def test_fr37_probes_are_twenty_pairs_with_unique_queries():
    """PROBES holds exactly 20 (query, target_text) pairs and no query repeats."""
    probes = rank_probe.PROBES
    assert len(probes) == 20
    for pair in probes:
        assert len(pair) == 2
        assert all(isinstance(s, str) and s.strip() for s in pair)
    queries = [q.strip().lower() for q, _ in probes]
    assert len(set(queries)) == 20


def test_fr37_each_probe_target_is_exactly_one_seed_item():
    """Every probe target is the exact text of exactly one item in eval/seed_v3.json."""
    texts = [i["text"] for i in real_seed()]
    for _, target in rank_probe.PROBES:
        assert texts.count(target) == 1, target


def test_fr37_at_least_eight_probes_share_no_content_word_with_target():
    """At least 8 of the 20 probes share no content word (after the store's stemmer) with their target."""
    hard = [
        q
        for q, target in rank_probe.PROBES
        if content_stems(q).isdisjoint(content_stems(target))
    ]
    assert len(hard) >= 8, hard


def test_fr37_evaluate_counts_hits_and_lists_misses(db):
    """evaluate returns hits, total and a miss entry (query, target, got) for a probe that cannot be found."""
    probes = (
        ("linear algebra", TINY_ITEMS[0]["text"]),
        ("dark mode", TINY_ITEMS[1]["text"]),
        ("zebra crossing", TINY_ITEMS[2]["text"]),
    )

    result = rank_probe.evaluate(TINY_ITEMS, probes)

    assert result["hits"] == 2
    assert result["total"] == 3
    assert len(result["misses"]) == 1
    miss = result["misses"][0]
    assert miss["query"] == "zebra crossing"
    assert miss["target"] == TINY_ITEMS[2]["text"]
    assert miss["got"] == []


def test_fr37_evaluate_miss_lists_returned_texts_in_order(db):
    """A miss's got lists the texts that search_memories returned instead of the target."""
    probes = (("linear algebra", TINY_ITEMS[1]["text"]),)

    result = rank_probe.evaluate(TINY_ITEMS, probes)

    assert result["hits"] == 0
    assert result["total"] == 1
    assert result["misses"][0]["got"] == [TINY_ITEMS[0]["text"]]


def test_fr37_evaluate_honours_k(db):
    """With the target as the weaker of two matches, k=1 is a miss and k=2 is a hit."""
    strong = item("python tips python tricks", 1)
    weak = item("I mostly write python when scripting small tools for work", 2)
    probes = (("python", weak["text"]),)

    at_one = rank_probe.evaluate([strong, weak], probes, k=1)
    assert (at_one["hits"], at_one["total"]) == (0, 1)
    assert at_one["misses"][0]["got"] == [strong["text"]]

    at_two = rank_probe.evaluate([strong, weak], probes, k=2)
    assert (at_two["hits"], at_two["total"]) == (1, 1)
    assert at_two["misses"] == []


def test_fr37_evaluate_reports_the_rank_of_each_hit(db):
    """evaluate returns, per probe in order, the 1-based rank of the target in the results or None for a miss, and the worst rank among the hits."""
    strong = item("python tips python tricks", 1)
    weak = item("I mostly write python when scripting small tools for work", 2)
    probes = (
        ("python", strong["text"]),
        ("python", weak["text"]),
        ("zebra crossing", strong["text"]),
    )

    result = rank_probe.evaluate([strong, weak], probes)

    assert result["ranks"] == [1, 2, None]
    assert result["worst_rank"] == 2
    assert result["hits"] == 2


def test_fr37_evaluate_worst_rank_is_none_without_hits(db):
    """With no hit there is no worst rank."""
    result = rank_probe.evaluate(
        TINY_ITEMS, (("zebra crossing", TINY_ITEMS[0]["text"]),)
    )

    assert result["ranks"] == [None]
    assert result["worst_rank"] is None


def test_fr37_evaluate_leaves_the_real_database_alone(db):
    """evaluate works on the current (temporary) DB_PATH and never touches data/assistant.db."""
    before = real_db_state()

    rank_probe.evaluate(TINY_ITEMS, (("dark mode", TINY_ITEMS[1]["text"]),))

    assert config.DB_PATH == db
    assert real_db_state() == before


def write_tiny_seed(tmp_path, monkeypatch):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(TINY_ITEMS), encoding="utf-8")
    monkeypatch.setattr("eval.config.V3_SEED_PATH", path)
    return path


def test_fr37_main_prints_hit_rate_ranks_and_misses(monkeypatch, tmp_path, capsys):
    """main prints the hit rate, the worst hit rank, the rank distribution, one line per probe with its rank, then one line per miss with query and target."""
    write_tiny_seed(tmp_path, monkeypatch)
    probes = (
        ("linear algebra", TINY_ITEMS[0]["text"]),
        ("dark mode", TINY_ITEMS[1]["text"]),
        ("zebra crossing", TINY_ITEMS[2]["text"]),
    )
    monkeypatch.setattr("eval.rank_probe.PROBES", probes)

    rank_probe.main()

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert lines[0] == "top-5 hit rate: 2/3 (67%)"
    assert lines[1] == "worst hit rank: 1"
    assert lines[2] == "ranks: 1:2 2:0 3:0 4:0 5:0 miss:1"
    assert "rank 1" in lines[3] and "linear algebra" in lines[3]
    assert "rank 1" in lines[4] and "dark mode" in lines[4]
    assert "miss" in lines[5] and "zebra crossing" in lines[5]
    assert lines[6].startswith("MISS")
    assert "zebra crossing" in lines[6]
    assert TINY_ITEMS[2]["text"] in lines[6]
    assert len(lines) == 7


def test_fr37_main_says_no_worst_rank_when_nothing_hits(monkeypatch, tmp_path, capsys):
    """With no hit at all the worst hit rank line says none, and every probe is a miss."""
    write_tiny_seed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "eval.rank_probe.PROBES", (("zebra crossing", TINY_ITEMS[2]["text"]),)
    )

    rank_probe.main()

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "top-5 hit rate: 0/1 (0%)"
    assert lines[1] == "worst hit rank: none"
    assert lines[2] == "ranks: 1:0 2:0 3:0 4:0 5:0 miss:1"


def test_fr37_main_restores_db_path_and_spares_real_database(
    monkeypatch, tmp_path, capsys
):
    """main uses a temporary DB_PATH, restores the original afterwards and leaves data/assistant.db untouched."""
    write_tiny_seed(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "eval.rank_probe.PROBES", (("dark mode", TINY_ITEMS[1]["text"]),)
    )
    original = config.DB_PATH
    before = real_db_state()

    rank_probe.main()

    assert config.DB_PATH == original
    assert real_db_state() == before
    assert "top-5 hit rate: 1/1 (100%)" in capsys.readouterr().out


def test_fr37_main_restores_db_path_when_seed_is_missing(monkeypatch, tmp_path):
    """A missing seed file raises, and server.config.DB_PATH is still the original value."""
    monkeypatch.setattr("eval.config.V3_SEED_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        "eval.rank_probe.PROBES", (("dark mode", TINY_ITEMS[1]["text"]),)
    )
    original = config.DB_PATH

    with pytest.raises(FileNotFoundError):
        rank_probe.main()

    assert config.DB_PATH == original
