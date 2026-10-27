import json

from eval import config
from eval.run_eval import timings_s

LAST_N = 10  # the live list has 10 questions


def read_last(n: int = LAST_N) -> list[dict]:
    """The last n logged queries, oldest first; the session writer's lines have an event and are
    not queries."""
    if not config.LOG_PATH.exists():
        return []
    lines = config.LOG_PATH.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if line.strip()]
    return [e for e in entries if "event" not in e][-n:]


def latency_s(entry: dict) -> float:
    return timings_s(entry)["total"]


def _cell(text: str | None) -> str:
    return " ".join((text or "").split()).replace("|", "/")


def format_table(entries: list[dict]) -> str:
    lines = [
        "| # | question | answer | latency s | error |",
        "| --- | --- | --- | --- | --- |",
    ]
    for n, e in enumerate(entries, 1):
        lines.append(
            f"| {n} | {_cell(e['question'])} | {_cell(e['answer'])} "
            f"| {latency_s(e):.1f} | {_cell(e['error'])} |"
        )
    return "\n".join(lines)


def main() -> None:
    entries = read_last()
    print(format_table(entries) if entries else "No queries logged yet.")


if __name__ == "__main__":
    main()
