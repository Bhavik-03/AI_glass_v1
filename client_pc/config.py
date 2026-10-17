SERVER_URL = "http://127.0.0.1:8000"
QUERY_TIMEOUT_S = 25
POLL_TIMEOUT_S = 20
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
SAMPLE_BYTES = 2
MAX_RECORD_S = 10
PRE_ROLL_S = 0.2
TONE_VOLUME = 0.3  # fraction of full scale
TONE_FADE_S = 0.01
PLAYBACK_TAIL_S = 0.2
# Each tone is a sequence of (frequency in Hz, duration in s) segments.
START_TONE = ((660, 0.08), (880, 0.08))
THINKING_TONE = ((440, 0.15),)
ERROR_TONE = ((300, 0.2), (200, 0.3))
# Name of a pynput.keyboard.Key member. Right Alt reports alt_gr on this laptop (after an
# extra ctrl_l press, which is ignored).
VOICE_KEY = "alt_gr"
LOOK_KEY = "ctrl_r"  # Right Ctrl: voice plus one screenshot taken at press
SCREENSHOT_MAX_SIDE_PX = 1280
SCREENSHOT_JPEG_QUALITY = (
    70  # chosen in the M9-T1 spike: about 76 KB, small text readable
)
MIN_RECORDING_S = 0.3
ERROR_MAX_CHARS = 200
POLL_INTERVAL_S = 10
LOG_LEVEL = "INFO"
