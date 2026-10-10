import io
import logging
import time
import wave

from faster_whisper import WhisperModel

from server import config

logger = logging.getLogger(__name__)
_model: WhisperModel | None = None


def load() -> None:
    """Build the whisper model once and warm it up; called from the FastAPI lifespan."""
    global _model
    _model = WhisperModel(
        config.STT_MODEL, device=config.STT_DEVICE, compute_type=config.STT_COMPUTE_TYPE
    )
    # The first CUDA transcription is slow (~2 s), so pay it at startup, not on the first question.
    t0 = time.perf_counter()
    transcribe(_silent_wav())
    logger.info("stt warm-up: %d ms", round((time.perf_counter() - t0) * 1000))


def transcribe(wav: bytes) -> str:
    """Turn question WAV bytes into text."""
    segments, _ = _model.transcribe(io.BytesIO(wav))
    return "".join(segment.text for segment in segments).strip()


def _silent_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * config.SAMPLE_RATE * config.STT_WARMUP_S)
    return buf.getvalue()
