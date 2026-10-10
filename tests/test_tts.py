"""TTS module tests (FR-11). A fake Piper voice is used: no model file, network or GPU."""

import io
import wave
from typing import ClassVar

import pytest

from server import config, tts

NATIVE_RATE = 22050
NATIVE_FRAMES = 22050


class FakeVoice:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize_wav(self, text, wav_file) -> None:
        self.texts.append(text)
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(NATIVE_RATE)
        pattern = b"\x10\x27\xf0\xd8"  # +10000, -10000 (non-zero)
        wav_file.writeframes(pattern * (NATIVE_FRAMES // 2))


class FakePiperVoice:
    load_calls: ClassVar[list] = []
    voice: ClassVar[FakeVoice]

    @classmethod
    def load(cls, path):
        cls.load_calls.append(path)
        return cls.voice


@pytest.fixture
def fake_piper(monkeypatch):
    FakePiperVoice.load_calls = []
    FakePiperVoice.voice = FakeVoice()
    monkeypatch.setattr(tts, "PiperVoice", FakePiperVoice)
    monkeypatch.setattr(tts, "_voice", None)
    return FakePiperVoice


def test_fr11_load_builds_voice_from_config(fake_piper, monkeypatch, tmp_path):
    """load() builds the Piper voice once from config.TTS_VOICE_PATH and keeps it in _voice."""
    path = tmp_path / "voice.onnx"
    monkeypatch.setattr(config, "TTS_VOICE_PATH", path)

    tts.load()

    assert len(fake_piper.load_calls) == 1
    assert fake_piper.load_calls[0] == path
    assert tts._voice is fake_piper.voice


def test_fr11_load_warms_up_with_one_synthesis(fake_piper):
    """load() synthesizes a short text once as a warm-up."""
    tts.load()

    assert len(fake_piper.voice.texts) == 1
    assert fake_piper.voice.texts[0].strip() != ""


def test_fr11_synthesize_returns_16k_mono_16bit_wav(fake_piper):
    """synthesize(text) returns a WAV that is 1 channel, 2-byte samples, 16000 Hz."""
    tts.load()

    out = tts.synthesize("Hello there.")

    with wave.open(io.BytesIO(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == config.SAMPLE_RATE == 16000
        assert w.getnframes() > 0


def test_fr11_synthesize_resamples_frame_count(fake_piper):
    """The 22050 Hz output is resampled: frame count is about 16000/22050 of the input."""
    tts.load()

    out = tts.synthesize("Hello there.")

    expected = round(NATIVE_FRAMES * 16000 / NATIVE_RATE)
    with wave.open(io.BytesIO(out), "rb") as w:
        assert abs(w.getnframes() - expected) <= 5
        assert w.readframes(w.getnframes()) != b"\x00" * (2 * w.getnframes())


def test_fr11_synthesize_passes_text_to_voice(fake_piper):
    """The voice receives exactly the text given to synthesize()."""
    tts.load()

    tts.synthesize("It is five o'clock.")

    assert fake_piper.voice.texts[-1] == "It is five o'clock."
