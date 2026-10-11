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
# Above the server's 20 s worst case and the client's 25 s, so the runner records a 500
# instead of giving up first.
QUERY_TIMEOUT_S = 30
# Gemini free tier allows 15 requests a minute, so each call gets 4 s.
SECONDS_PER_CALL = 4
CLIENT_MODULE = "client_pc.client"
PROCESS_LIST_TIMEOUT_S = 10
# "in N minutes" is worked out from the time in the system instruction, a few seconds
# before the reminder is stored; fixed clock times must land on the minute.
DUE_AT_TOLERANCE_S = 60
DUE_IN_TOLERANCE_S = 120
RESULTS_DIR = ROOT / "eval" / "results"
# Quality targets from spec.md.
GROUP_PASS_MIN = 0.8
MEDIAN_TOTAL_MAX_S = 15
TRANSCRIPTION_MIN = 0.9
