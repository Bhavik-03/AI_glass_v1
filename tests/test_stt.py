"""STT module tests (FR-4). A fake model is used: no download, GPU or CUDA."""

import io
import wave
from types import SimpleNamespace

from server import config, stt


def make_wav(seconds: int = 1, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * rate * seconds)
    return buf.getvalue()


class FakeModel:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts
        self.received: bytes | None = None

    def transcribe(self, audio):
        self.received = audio.read()
        segments = iter([SimpleNamespace(text=t) for t in self.texts])
        return segments, SimpleNamespace()


def test_fr4_load_builds_model_from_config(monkeypatch):
    """load() builds WhisperModel from STT_MODEL, STT_DEVICE, STT_COMPUTE_TYPE in config."""
    calls = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(stt, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(stt, "_model", None)
    monkeypatch.setattr(config, "STT_MODEL", "tiny.en")
    monkeypatch.setattr(config, "STT_DEVICE", "cpu")
    monkeypatch.setattr(config, "STT_COMPUTE_TYPE", "int8")

    stt.load()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("tiny.en",)
    assert kwargs == {"device": "cpu", "compute_type": "int8"}
    assert isinstance(stt._model, FakeWhisperModel)


def test_fr4_transcribe_passes_wav_bytes_to_model(monkeypatch):
    """transcribe(wav) hands the WAV bytes to the model unchanged."""
    fake = FakeModel([" hello"])
    monkeypatch.setattr(stt, "_model", fake)
    wav = make_wav()

    stt.transcribe(wav)

    assert fake.received == wav


def test_fr4_transcribe_joins_segment_texts(monkeypatch):
    """transcribe returns the segment texts joined into one stripped string."""
    monkeypatch.setattr(stt, "_model", FakeModel([" What time", " is it?"]))

    assert stt.transcribe(make_wav()) == "What time is it?"
