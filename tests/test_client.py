"""Recorder tests for the PC client (FR-1). Fake mic: no sound device is used."""

import array
import io
import wave

import pytest

from client_pc import config
from client_pc.client import Recorder

CHUNK = 1600  # samples per fed chunk (0.1 s)


def chunk(value: int, samples: int = CHUNK) -> bytes:
    return array.array("h", [value] * samples).tobytes()


def samples_of(wav_bytes: bytes) -> list[int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        data = w.readframes(w.getnframes())
    out = array.array("h")
    out.frombytes(data)
    return list(out)


class FakeStream:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0
        self.closed = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1


@pytest.fixture
def factory():
    calls: list[dict] = []
    streams: list[FakeStream] = []

    def make(**kwargs):
        calls.append(kwargs)
        s = FakeStream()
        streams.append(s)
        return s

    make.calls = calls
    make.streams = streams
    return make


def test_fr1_open_creates_one_stream_with_audio_format(factory):
    """The recorder opens one 16 kHz mono 16-bit input stream at client start."""
    rec = Recorder(stream_factory=factory)
    rec.open()
    assert len(factory.calls) == 1
    kw = factory.calls[0]
    assert kw["samplerate"] == config.SAMPLE_RATE == 16000
    assert kw["channels"] == config.CHANNELS == 1
    assert kw["dtype"] == "int16"
    assert callable(kw["callback"])
    assert factory.streams[0].started == 1


def test_fr1_open_twice_opens_only_one_stream(factory):
    """Starting the stream is safe to call twice."""
    rec = Recorder(stream_factory=factory)
    rec.open()
    rec.open()
    assert len(factory.calls) == 1
    assert factory.streams[0].started == 1


def test_fr1_close_stops_and_closes_stream(factory):
    """Stopping the stream stops and closes it."""
    rec = Recorder(stream_factory=factory)
    rec.open()
    rec.close()
    assert factory.streams[0].stopped == 1
    assert factory.streams[0].closed == 1


def test_fr1_close_twice_is_safe(factory):
    """Stopping the stream is safe to call twice."""
    rec = Recorder(stream_factory=factory)
    rec.open()
    rec.close()
    rec.close()
    assert factory.streams[0].closed == 1


def test_fr1_close_before_open_is_safe(factory):
    """Closing a recorder that was never opened does not raise."""
    Recorder(stream_factory=factory).close()
    assert factory.calls == []


def test_fr1_stream_callback_feeds_recorder(factory):
    """Frames from the mic stream callback reach the recording."""
    rec = Recorder(stream_factory=factory)
    rec.open()
    rec.start_recording()
    factory.calls[0]["callback"](memoryview(chunk(4)), CHUNK, None, None)
    assert samples_of(rec.stop_recording()) == [4] * CHUNK


def test_fr1_audio_before_preroll_window_is_excluded():
    """Audio older than the 0.2 s pre-roll window is not in the recording."""
    rec = Recorder()
    for v in (1, 2, 3, 4, 5):
        rec.on_audio(chunk(v))
    assert rec.start_recording() is True
    wav = rec.stop_recording()
    s = samples_of(wav)
    assert 1 not in s and 2 not in s and 3 not in s


def test_fr1_preroll_is_included_at_start():
    """The last 0.2 s before the key press starts the recording."""
    rec = Recorder()
    for v in (1, 2, 3, 4, 5):
        rec.on_audio(chunk(v))
    rec.start_recording()
    rec.on_audio(chunk(9))
    s = samples_of(rec.stop_recording())
    preroll = int(config.PRE_ROLL_S * config.SAMPLE_RATE)
    assert s[:preroll] == [4] * CHUNK + [5] * CHUNK
    assert s[preroll:] == [9] * CHUNK


def test_fr1_following_frames_are_all_kept():
    """A key press keeps the pre-roll plus all following frames."""
    rec = Recorder()
    rec.on_audio(chunk(1))
    rec.start_recording()
    for v in (7, 8, 9):
        rec.on_audio(chunk(v))
    s = samples_of(rec.stop_recording())
    assert s == [1] * CHUNK + [7] * CHUNK + [8] * CHUNK + [9] * CHUNK


def test_fr1_recording_flag_follows_start_and_stop():
    """recording is True from a successful start until stop."""
    rec = Recorder()
    assert rec.recording is False
    rec.start_recording()
    assert rec.recording is True
    rec.stop_recording()
    assert rec.recording is False


def test_fr1_recording_stops_at_max_record_s():
    """Recording is capped at 10 s of audio and reports full."""
    rec = Recorder()
    rec.start_recording()
    assert rec.full is False
    for _ in range(120):  # 12 s fed
        rec.on_audio(chunk(3))
    assert rec.full is True
    s = samples_of(rec.stop_recording())
    assert len(s) == config.MAX_RECORD_S * config.SAMPLE_RATE


def test_fr1_release_stops_and_later_frames_are_not_included():
    """Releasing the key stops the recording; later frames only feed the pre-roll."""
    rec = Recorder()
    rec.start_recording()
    rec.on_audio(chunk(1))
    first = samples_of(rec.stop_recording())
    assert first == [1] * CHUNK
    for v in (6, 7, 8):
        rec.on_audio(chunk(v))
    rec.start_recording()
    second = samples_of(rec.stop_recording())
    assert second == [7] * CHUNK + [8] * CHUNK
    assert 1 not in second


def test_fr1_second_press_while_recording_is_ignored():
    """A second press while already recording returns False and keeps the buffer."""
    rec = Recorder()
    rec.on_audio(chunk(1))
    assert rec.start_recording() is True
    rec.on_audio(chunk(2))
    assert rec.start_recording() is False
    assert rec.recording is True
    rec.on_audio(chunk(3))
    s = samples_of(rec.stop_recording())
    assert s == [1] * CHUNK + [2] * CHUNK + [3] * CHUNK


def test_fr1_stop_when_not_recording_returns_none():
    """Stopping without a recording returns None."""
    rec = Recorder()
    assert rec.stop_recording() is None
    rec.start_recording()
    rec.stop_recording()
    assert rec.stop_recording() is None


def test_fr1_output_is_16khz_mono_16bit_wav():
    """The returned WAV is 16 kHz, mono, 16-bit."""
    rec = Recorder()
    rec.start_recording()
    rec.on_audio(chunk(0))
    wav = rec.stop_recording()
    with wave.open(io.BytesIO(wav), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
