from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = "127.0.0.1"
PORT = 8000
LLM_MODEL = "gemini-3.8-flash"
LOG_PATH = ROOT / "logs" / "queries.jsonl"
