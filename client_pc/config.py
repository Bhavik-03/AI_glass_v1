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
