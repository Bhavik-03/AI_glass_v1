"""Recorder tests for the PC client (FR-1). Fake mic: no sound device is used."""

import array
import io
import math
import wave
from itertools import pairwise

import pytest

from client_pc import config
from client_pc.client import Player, Recorder, make_tone

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


# ---- FR-2: sounds (tones and WAV playback). Fake output stream: no sound device. ----

TONES = {
    "start": "START_TONE",
    "thinking": "THINKING_TONE",
    "error": "ERROR_TONE",
}


class FakeOutputStream:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.started = 0
        self.stopped = 0
        self.closed = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def close(self) -> None:
        self.closed += 1

    def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))

    @property
    def written(self) -> bytes:
        return b"".join(self.writes)


@pytest.fixture
def out_factory():
    calls: list[dict] = []
    streams: list[FakeOutputStream] = []

    def make(**kwargs):
        calls.append(kwargs)
        s = FakeOutputStream()
        streams.append(s)
        return s

    make.calls = calls
    make.streams = streams
    return make


@pytest.fixture
def player(out_factory):
    p = Player(stream_factory=out_factory)
    p.open()
    return p


def pcm(data: bytes) -> list[int]:
    a = array.array("h")
    a.frombytes(data)
    return list(a)


def silence_tail() -> bytes:
    return bytes(int(config.PLAYBACK_TAIL_S * config.SAMPLE_RATE) * config.SAMPLE_BYTES)


def split_segments(samples: list[int], tone) -> list[tuple[float, list[int]]]:
    out = []
    pos = 0
    for freq, dur in tone:
        n = round(dur * config.SAMPLE_RATE)
        out.append((freq, samples[pos : pos + n]))
        pos += n
    return out


def zc_freq(seg: list[int]) -> float:
    crossings = sum(
        1 for a, b in pairwise(seg) if (a < 0 <= b) or (a > 0 >= b) or (a < 0 and b > 0)
    )
    return crossings / 2 / (len(seg) / config.SAMPLE_RATE)


def tone_cfg(name: str):
    return getattr(config, TONES[name])


def wav_of(samples: list[int], rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(array.array("h", samples).tobytes())
    return buf.getvalue()


def test_fr2_open_creates_one_started_output_stream(out_factory):
    """One 16 kHz mono 16-bit output stream is created and started at client start."""
    p = Player(stream_factory=out_factory)
    p.open()
    assert len(out_factory.calls) == 1
    kw = out_factory.calls[0]
    assert kw["samplerate"] == 16000
    assert kw["channels"] == 1
    assert kw["dtype"] == "int16"
    assert out_factory.streams[0].started == 1


def test_fr2_open_twice_opens_only_one_stream(out_factory):
    """Opening the player twice does nothing the second time."""
    p = Player(stream_factory=out_factory)
    p.open()
    p.open()
    assert len(out_factory.calls) == 1
    assert out_factory.streams[0].started == 1


def test_fr2_close_stops_and_closes_stream(out_factory):
    """Closing the player stops and closes the stream."""
    p = Player(stream_factory=out_factory)
    p.open()
    p.close()
    assert out_factory.streams[0].stopped == 1
    assert out_factory.streams[0].closed == 1


def test_fr2_close_twice_is_safe(out_factory):
    """Closing the player twice does not raise or close the stream twice."""
    p = Player(stream_factory=out_factory)
    p.open()
    p.close()
    p.close()
    assert out_factory.streams[0].closed == 1


def test_fr2_close_before_open_is_safe(out_factory):
    """Closing a player that was never opened does not raise."""
    Player(stream_factory=out_factory).close()
    assert out_factory.calls == []


def test_fr2_one_persistent_stream_is_reused_for_all_sounds(player, out_factory):
    """Tones and WAV playback all use the one stream, so there is no start delay."""
    player.play_start()
    player.play_thinking()
    player.play_error()
    player.play_wav(wav_of([5] * 160))
    assert len(out_factory.calls) == 1
    assert out_factory.streams[0].started == 1
    assert len(out_factory.streams[0].writes) >= 4


@pytest.mark.parametrize("name", ["start", "thinking", "error"])
def test_fr2_each_tone_writes_tone_plus_silence_tail(player, out_factory, name):
    """Each play_* writes exactly its generated tone followed by the silence tail."""
    getattr(player, f"play_{name}")()
    expected = make_tone(tone_cfg(name)) + silence_tail()
    assert out_factory.streams[0].written == expected


@pytest.mark.parametrize("name", ["start", "thinking", "error"])
def test_fr2_tone_is_16bit_mono_with_expected_length(name):
    """A tone is 16-bit PCM whose length is the sum of its segment durations."""
    data = make_tone(tone_cfg(name))
    assert len(data) % config.SAMPLE_BYTES == 0
    expected = sum(round(d * config.SAMPLE_RATE) for _, d in tone_cfg(name))
    assert abs(len(data) // config.SAMPLE_BYTES - expected) <= len(tone_cfg(name))


def test_fr2_three_tones_are_distinguishable():
    """Start, thinking and error tones differ pairwise in pitch (>=100 Hz) or length (>=0.1 s)."""
    info = {}
    blobs = {}
    for name in TONES:
        blobs[name] = make_tone(tone_cfg(name))
        s = pcm(blobs[name])
        first = split_segments(s, tone_cfg(name))[0][1]
        info[name] = (zc_freq(first), len(s) / config.SAMPLE_RATE)
    assert len(set(blobs.values())) == 3
    names = list(TONES)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            df = abs(info[a][0] - info[b][0])
            dt = abs(info[a][1] - info[b][1])
            assert df >= 100 or dt >= 0.1, (a, b, info)


@pytest.mark.parametrize("name", ["start", "thinking", "error"])
def test_fr2_tone_segment_frequencies_match_config(name):
    """Each segment is a sine at its configured frequency."""
    s = pcm(make_tone(tone_cfg(name)))
    for freq, seg in split_segments(s, tone_cfg(name)):
        assert abs(zc_freq(seg) - freq) <= freq * 0.1


@pytest.mark.parametrize("name", ["start", "thinking", "error"])
def test_fr2_tone_segments_start_and_end_at_zero(name):
    """Every tone segment fades in from and out to 0, so there are no clicks at its edges."""
    s = pcm(make_tone(tone_cfg(name)))
    for _, seg in split_segments(s, tone_cfg(name)):
        assert seg[0] == 0
        assert seg[-1] == 0
        peak = max(abs(x) for x in seg)
        assert max(abs(x) for x in seg[1:4]) < peak
        assert max(abs(x) for x in seg[-4:-1]) < peak


@pytest.mark.parametrize("name", ["start", "thinking", "error"])
def test_fr2_tone_has_no_click_steps(name):
    """No sample-to-sample jump exceeds that of a pure sine at the same peak and frequency."""
    tone = tone_cfg(name)
    s = pcm(make_tone(tone))
    amp = config.TONE_VOLUME * 32767
    top = max(f for f, _ in tone)
    limit = 2 * amp * math.sin(math.pi * top / config.SAMPLE_RATE) * 1.05
    steps = max(abs(b - a) for a, b in pairwise(s))
    assert steps <= limit


@pytest.mark.parametrize("volume", [0.5, 0.25])
def test_fr2_tone_peak_scales_with_tone_volume(monkeypatch, volume):
    """The tone's peak amplitude follows TONE_VOLUME times full scale."""
    monkeypatch.setattr(config, "TONE_VOLUME", volume)
    s = pcm(make_tone(config.THINKING_TONE))
    peak = max(abs(x) for x in s)
    assert volume * 32767 * 0.95 <= peak <= volume * 32767 * 1.02


def test_fr2_default_tone_volume_is_moderate():
    """The default TONE_VOLUME is above 0 and at most 0.5 of full scale."""
    assert 0 < config.TONE_VOLUME <= 0.5


def test_fr2_play_wav_writes_pcm_plus_silence_tail(player, out_factory):
    """play_wav writes the WAV's exact PCM frames followed by the silence tail."""
    samples = [(i * 37) % 2000 - 1000 for i in range(3200)]
    player.play_wav(wav_of(samples))
    expected = array.array("h", samples).tobytes() + silence_tail()
    assert out_factory.streams[0].written == expected


@pytest.mark.parametrize(
    "bad",
    [
        wav_of([1] * 800, rate=8000),
        wav_of([1] * 800, channels=2),
    ],
    ids=["8khz", "stereo"],
)
def test_fr2_play_wav_rejects_wrong_format_and_writes_nothing(player, out_factory, bad):
    """A WAV that is not 16 kHz mono 16-bit raises ValueError and nothing is played."""
    with pytest.raises(ValueError):
        player.play_wav(bad)
    assert out_factory.streams[0].writes == []
