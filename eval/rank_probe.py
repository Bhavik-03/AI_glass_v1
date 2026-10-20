"""Top-5 ranking probe for search_memories over the v3 seed (FR-37).

Run: .venv/bin/python -m eval.rank_probe

It measures ranking only: whether the right item is among the 5 that reach Gemini. Whether
Gemini then uses what it is given is a separate failure that only the full v3 eval catches.
Re-run it whenever the search implementation changes. A rate below 90% is the signal to
propose the local embedding model.

The probes were written from the seed's meaning before the first run and are not edited
afterwards. They never go into questions_v3.json.
"""

import json
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from eval import config as eval_config
from server import config, store

# FR-37: at most 5 items reach Gemini.
TOP_K = 5

# (question, exact text of the seed item it should retrieve).
PROBES = (
    # Hard: no content word shared with the target.
    (
        "the thing about making models smaller",
        "Quantization to 4-bit lets big networks fit on the laptop GPU",
    ),
    (
        "why my run stopped getting better",
        "Training loss plateaued because the learning rate was too high",
    ),
    (
        "what graphics hardware do I have",
        "Laptop has an RTX 4060 GPU with 8 GB memory",
    ),
    (
        "who in my family is taking an entrance test",
        "Younger sister is preparing for the JEE exam",
    ),
    (
        "the way language networks decide which tokens to focus on",
        "Discussed how attention lets transformers weigh earlier words in a sentence",
    ),
    (
        "what new coding skill am I picking up for fun",
        "Favourite programming language is Python, learning Rust on the side",
    ),
    (
        "when do I have to hand in the labelling tool",
        "Annotation project deadline is the first week of November",
    ),
    (
        "what was my plan for the order of work on the project",
        "Decided to finish the dataset cleaning before touching model code",
    ),
    # Realistic mixed phrasings.
    (
        "what is my annotation project about",
        "Annotation project: building a tool to label medical images",
    ),
    (
        "what did we discuss about gradient descent",
        "Went through gradient descent and why momentum speeds convergence",
    ),
    (
        "which framework do I use for coursework",
        "Switched from TensorFlow to PyTorch for all coursework",
    ),
    ("where do I live", "Lives in Nagpur and commutes to college by metro"),
    (
        "when does the robotics club meet",
        "Part of the college robotics club, meets Thursdays",
    ),
    (
        "what units and currency do I prefer",
        "Prefers metric units and Indian rupees",
    ),
    (
        "what happened with my model overfitting",
        "Overfitting appeared after epoch twelve; added dropout and early stopping",
    ),
    (
        "do I like watching long videos",
        "Finds long videos tiring; prefers reading papers with figures",
    ),
    (
        "how big is my dataset",
        "Dataset has about 4,000 chest X-ray images with radiologist labels",
    ),
    (
        "what did we say about precision and recall",
        "Explained the difference between precision and recall with a spam example",
    ),
    (
        "when do my final exams begin",
        "Final semester exams start on the 9th of December",
    ),
    (
        "what thesis topic did I pick",
        "Thesis topic is efficient fine-tuning of small language models",
    ),
)


def evaluate(
    items: list[dict], probes: Sequence[tuple[str, str]], k: int = TOP_K
) -> dict:
    """Load `items` into the current database and find each probe's target in the top `k`
    results of `store.search_memories`. `ranks` holds, per probe in order, the target's
    1-based rank or None for a miss."""
    store.init()
    for entry in items:
        store.remember(entry["text"], entry["type"], entry["created_at"])
    ranks, misses = [], []
    for query, target in probes:
        got = [m["text"] for m in store.search_memories(query, k)]
        rank = got.index(target) + 1 if target in got else None
        ranks.append(rank)
        if rank is None:
            misses.append({"query": query, "target": target, "got": got})
    hit_ranks = [rank for rank in ranks if rank]
    return {
        "hits": len(hit_ranks),
        "total": len(probes),
        "misses": misses,
        "ranks": ranks,
        "worst_rank": max(hit_ranks, default=None),
    }


def main() -> None:
    items = json.loads(eval_config.V3_SEED_PATH.read_text(encoding="utf-8"))
    probes = PROBES
    original = config.DB_PATH
    # A throwaway database: the probe never touches data/assistant.db.
    with tempfile.TemporaryDirectory() as tmp:
        config.DB_PATH = Path(tmp) / "rank_probe.db"
        try:
            result = evaluate(items, probes)
        finally:
            config.DB_PATH = original
    hits, total = result["hits"], result["total"]
    print(f"top-{TOP_K} hit rate: {hits}/{total} ({round(100 * hits / total)}%)")
    print(f"worst hit rank: {result['worst_rank'] or 'none'}")
    counts = Counter(result["ranks"])
    spread = " ".join(f"{rank}:{counts[rank]}" for rank in range(1, TOP_K + 1))
    print(f"ranks: {spread} miss:{counts[None]}")
    for (query, _), rank in zip(probes, result["ranks"]):
        print(f"{f'rank {rank}' if rank else 'miss':<7} {query}")
    for miss in result["misses"]:
        print(
            f"MISS {miss['query']!r} -> expected {miss['target']!r}; got {miss['got']}"
        )


if __name__ == "__main__":
    main()
