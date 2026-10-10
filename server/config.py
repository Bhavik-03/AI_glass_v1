from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOST = "127.0.0.1"
PORT = 8000
LLM_MODEL = "gemini-3.8-flash"
TIMEZONE = "Asia/Kolkata"
HOME_CITY = "Pune"
LOG_PATH = ROOT / "logs" / "queries.jsonl"
STT_MODEL = "small.en"
STT_DEVICE = "cuda"
STT_COMPUTE_TYPE = "float16"
SAMPLE_RATE = 16000
STT_WARMUP_S = 1
