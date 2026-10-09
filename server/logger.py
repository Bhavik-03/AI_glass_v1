import json
import sys
from datetime import datetime

from server import config


def log_query(record: dict) -> None:
    """Append one JSONL line for a query; never raises, so logging can't fail a request."""
    try:
        line = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            **record,
        }
        config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with config.LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as e:
        print(f"logger: {e}", file=sys.stderr)
