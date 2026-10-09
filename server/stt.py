import io

from faster_whisper import WhisperModel

from server import config

_model: WhisperModel | None = None


def load() -> None:
    """Build the whisper model once; called from the FastAPI lifespan."""
    global _model
    _model = WhisperModel(
        config.STT_MODEL, device=config.STT_DEVICE, compute_type=config.STT_COMPUTE_TYPE
    )


def transcribe(wav: bytes) -> str:
    """Turn question WAV bytes into text."""
    segments, _ = _model.transcribe(io.BytesIO(wav))
    return "".join(segment.text for segment in segments).strip()
