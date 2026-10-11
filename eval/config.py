from pathlib import Path

from client_pc import config as client_config
from server import config as server_config

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
CLIP_DIR = ROOT / "data" / "eval"
MARKER_PATH = CLIP_DIR / "restore-pending"
DB_PATH = server_config.DB_PATH
LOG_PATH = server_config.LOG_PATH
SERVER_URL = client_config.SERVER_URL
QUERY_TIMEOUT_S = client_config.QUERY_TIMEOUT_S
# Gemini free tier allows 15 requests a minute, so each call gets 4 s.
SECONDS_PER_CALL = 4
CLIENT_MODULE = "client_pc.client"
PROCESS_LIST_TIMEOUT_S = 10
