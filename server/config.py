import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

HOST = "127.0.0.1"
PORT = 8000
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = "gemini-3.5-flash-lite"
LLM_TIMEOUT_S = 10
LLM_DEADLINE_S = 15
LLM_THINKING_LEVEL = "MINIMAL"
MAX_TOOL_ROUNDS = 3
TIMEZONE = "Asia/Kolkata"
HOME_CITY = "Pune"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
SEARCH_MAX_RESULTS = 5
SEARCH_TIMEOUT_S = 5
ERROR_MAX_CHARS = 200
LOG_LEVEL = "INFO"
LOG_PATH = ROOT / "logs" / "queries.jsonl"
DB_PATH = ROOT / "data" / "assistant.db"
DB_TIMEOUT_S = 5
MISSED_AFTER_S = 60
STT_MODEL = "small.en"
STT_DEVICE = "cuda"
STT_COMPUTE_TYPE = "float16"
SAMPLE_RATE = 16000
STT_WARMUP_S = 1
TTS_VOICE_PATH = ROOT / "models" / "en_US-lessac-medium.onnx"
TTS_WARMUP_TEXT = "Ready."
