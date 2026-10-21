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
LLM_FINAL_DEADLINE_S = 18
LLM_FINAL_START_MAX_S = 8
LLM_THINKING_LEVEL = "MINIMAL"
MAX_TOOL_ROUNDS = 3
ANSWER_MAX_SENTENCES = 3
ANSWER_MAX_WORDS = 60
LIST_MAX_ITEMS = 5
LEARNED_DAYS = 7
LEARNED_MAX_NAMES = 5
QUIZ_MAX_CONCEPTS = 3
PROFILE_SCHEMA_PATH = ROOT / "config" / "profile_schema.json"
PROFILE_VALUES_PATH = ROOT / "data" / "profile.json"
PROFILE_MAX_LINES = 40
PROFILE_LINE_CHARS = 100
GOAL_STALE_DAYS = 31
GOAL_STALE_SLOT = "goal_now"
GOAL_STALE_LINE = (
    "By the way, your goal for the month was set {days} days ago. Does it still hold?"
)
MEMORY_MAX_WORDS = 12
MEMORY_RECALL_MAX = 5
MEMORY_LIST_MAX = 5
MEMORY_SAME_THRESHOLD = 0.9
QUIZ_ANSWER_WAIT_S = 300
SETUP_SLOTS = ("identity", "goal_now", "goal_long", "exploring", "style", "constraints")
SETUP_STOP_PHRASE = "stop setup"
# Whisper splits "setup" in two ("Stop. Set up."): "stop" must come right before it.
SETUP_STOP_PATTERN = r"\bstop\s+set\s*up\b"
SETUP_ANSWER_WAIT_S = 300
# Whole phrases, as the normalised transcript: a yes commits a proposal, a no declines it.
PROPOSAL_YES = frozenset(
    {
        "yes",
        "yeah",
        "yep",
        "sure",
        "okay",
        "ok",
        "yes please",
        "please do",
        "go ahead",
        "do it",
    }
)
PROPOSAL_NO = frozenset(
    {"no", "nope", "no thanks", "no thank you", "not now", "never mind", "nevermind"}
)
QUIZ_QUESTION = "Explain {name} in one sentence."
QUIZ_STOP_PHRASE = "stop quiz"
WIPE_REQUEST_PHRASE = "wipe my memories"
WIPE_CONFIRM_PHRASE = "yes wipe everything"
SESSION_TTL_S = 120
SESSION_MAX_TURNS = 5
IMAGE_MAX_BYTES = 2_000_000
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
# Vocabulary hint for whisper: the assistant's own command words and the home city only.
STT_INITIAL_PROMPT = (
    f"Note, notes, remind me, reminder, reminders, cancel. {HOME_CITY}."
)
TTS_VOICE_PATH = ROOT / "models" / "en_US-lessac-medium.onnx"
TTS_WARMUP_TEXT = "Ready."
