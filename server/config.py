import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

HOST = "127.0.0.1"
PORT = 8000
LLM_MODEL = "gemini-3.8-flash"
TIMEZONE = "Asia/Kolkata"
HOME_CITY = "Pune"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SEARCH_MAX_RESULTS = 5
SEARCH_TIMEOUT_S = 5
LOG_PATH = ROOT / "logs" / "queries.jsonl"
STT_MODEL = "small.en"
STT_DEVICE = "cuda"
STT_COMPUTE_TYPE = "float16"
SAMPLE_RATE = 16000
STT_WARMUP_S = 1
