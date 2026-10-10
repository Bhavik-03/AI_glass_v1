import audioop  # removed in Python 3.13: switch to another resampler before upgrading
import io
import wave

from piper import PiperVoice

from server import config

_voice: PiperVoice | None = None


def load() -> None:
    """Build the Piper voice once and warm it up; called from the FastAPI lifespan."""
    global _voice
    _voice = PiperVoice.load(config.TTS_VOICE_PATH)
    # The first synthesis can be slow while the model file is cold, so pay it at startup.
    synthesize(config.TTS_WARMUP_TEXT)


def synthesize(text: str) -> bytes:
    """Turn answer text into a 16 kHz mono 16-bit WAV."""
    native = io.BytesIO()
    with wave.open(native, "wb") as w:
        _voice.synthesize_wav(text, w)
    native.seek(0)
    with wave.open(native, "rb") as r:
        pcm = r.readframes(r.getnframes())
        channels, width, rate = r.getnchannels(), r.getsampwidth(), r.getframerate()
    pcm, _ = audioop.ratecv(pcm, width, channels, rate, config.SAMPLE_RATE, None)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)
    return out.getvalue()
