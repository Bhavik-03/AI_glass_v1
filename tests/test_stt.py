"""STT module tests (FR-4). A fake model is used: no download, GPU or CUDA."""

import io
import json
import logging
import re
import wave
from pathlib import Path
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
        self.initial_prompt: str | None = None

    def transcribe(self, audio, initial_prompt=None):
        self.received = audio.read()
        self.initial_prompt = initial_prompt
        segments = iter([SimpleNamespace(text=t) for t in self.texts])
        return segments, SimpleNamespace()


def test_fr4_load_builds_model_from_config(monkeypatch):
    """load() builds WhisperModel from STT_MODEL, STT_DEVICE, STT_COMPUTE_TYPE in config."""
    calls = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

        def transcribe(self, audio, initial_prompt=None):
            return iter([]), SimpleNamespace()

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


def test_fr4_load_warms_up_with_silent_clip(monkeypatch):
    """After building the model, load() transcribes one silent WAV clip as a warm-up."""
    received = []

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, initial_prompt=None):
            received.append(audio.read())
            return iter([]), SimpleNamespace()

    monkeypatch.setattr(stt, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(stt, "_model", None)

    stt.load()

    assert len(received) == 1
    with wave.open(io.BytesIO(received[0]), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == config.SAMPLE_RATE
        assert w.getnframes() == config.SAMPLE_RATE * config.STT_WARMUP_S
        frames = w.readframes(w.getnframes())
    assert frames == b"\x00" * len(frames)


def test_fr4_load_logs_warmup_time(monkeypatch, caplog, capsys):
    """load() logs one INFO 'stt warm-up: <ms> ms' on logger server.stt; nothing goes to stdout or stderr."""

    class FakeWhisperModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, audio, initial_prompt=None):
            return iter([]), SimpleNamespace()

    monkeypatch.setattr(stt, "WhisperModel", FakeWhisperModel)
    monkeypatch.setattr(stt, "_model", None)

    caplog.set_level(logging.INFO, logger="server.stt")

    stt.load()

    records = [
        r
        for r in caplog.records
        if r.name == "server.stt" and r.levelno == logging.INFO
    ]
    assert len(records) == 1
    assert re.search(r"stt warm-up: \d+ ms", records[0].getMessage())
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_fr4_transcribe_passes_wav_bytes_to_model(monkeypatch):
    """transcribe(wav) hands the WAV bytes to the model unchanged."""
    fake = FakeModel([" hello"])
    monkeypatch.setattr(stt, "_model", fake)
    wav = make_wav()

    stt.transcribe(wav)

    assert fake.received == wav


def test_fr4_transcribe_passes_initial_prompt_from_config(monkeypatch):
    """transcribe passes initial_prompt=config.STT_INITIAL_PROMPT to the model."""
    fake = FakeModel([" hello"])
    monkeypatch.setattr(stt, "_model", fake)
    monkeypatch.setattr(config, "STT_INITIAL_PROMPT", "sentinel prompt", raising=False)

    stt.transcribe(make_wav())

    assert fake.initial_prompt == "sentinel prompt"


def test_fr4_initial_prompt_has_command_words_and_home_city():
    """STT_INITIAL_PROMPT is a non-empty str with the command words and the home city."""
    prompt = config.STT_INITIAL_PROMPT
    assert isinstance(prompt, str)
    assert prompt.strip()
    lowered = prompt.lower()
    for word in ("note", "notes", "remind me", "reminder", "reminders", "cancel"):
        assert word in lowered
    assert config.HOME_CITY.lower() in lowered


def test_fr4_initial_prompt_has_no_eval_question_words():
    """The prompt holds only command words and the city: no content words from the eval questions."""
    path = Path(__file__).resolve().parent.parent / "eval" / "questions.json"
    questions = json.loads(path.read_text(encoding="utf-8"))
    spoken = " ".join(q["spoken"].lower() for q in questions)
    forbidden = [
        "wings",
        "fire",
        "isro",
        "rupee",
        "dollar",
        "soldering",
        "wire",
        "fuse",
        "motor",
        "jumper",
        "battery",
        "sensor",
        "calibrate",
        "lab",
        "laptop",
        "mountain",
        "moon",
        "football",
    ]
    prompt_words = set(re.findall(r"[a-z]+", config.STT_INITIAL_PROMPT.lower()))
    spoken_words = set(re.findall(r"[a-z]+", spoken))
    for word in forbidden:
        if word in spoken_words:
            assert word not in prompt_words, word


def test_fr4_transcribe_joins_segment_texts(monkeypatch):
    """transcribe returns the segment texts joined into one stripped string."""
    monkeypatch.setattr(stt, "_model", FakeModel([" What time", " is it?"]))

    assert stt.transcribe(make_wav()) == "What time is it?"
