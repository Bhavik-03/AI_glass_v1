"""Recorder tests for the PC client (FR-1). Fake mic: no sound device is used."""

import array
import io
import logging
import math
import threading
import wave
from itertools import pairwise

import httpx
import pytest
from pynput import keyboard

from client_pc import config
from client_pc.client import (
    Client,
    Player,
    QueryError,
    QueryTimeout,
    Recorder,
    ServerUnreachable,
    make_tone,
    send_query,
)

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


# ---- FR-3: send_query. httpx.MockTransport: no network, no real server. ----

ANSWER_WAV = wav_of([3, -3] * 400)
QUESTION_WAV = wav_of([11, -11, 5] * 300)


def answer_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200, content=ANSWER_WAV, headers={"content-type": "audio/wav"}
    )


def capture(seen: list[httpx.Request], respond=answer_handler):
    def handler(request: httpx.Request) -> httpx.Response:
        request.read()
        seen.append(request)
        return respond(request)

    return handler


def fixed_response(status: int, **kwargs):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, **kwargs)

    return handler


def raising(exc: Exception):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


def query_with(handler, wav: bytes = QUESTION_WAV) -> bytes:
    return send_query(wav, transport=httpx.MockTransport(handler))


def test_fr3_posts_to_query_path():
    """send_query makes one POST to /query."""
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert len(seen) == 1
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/query"


def test_fr3_request_goes_to_configured_server():
    """The request goes to the configured server URL."""
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert str(seen[0].url) == config.SERVER_URL.rstrip("/") + "/query"


def test_fr3_body_is_multipart_with_audio_part_of_type_wav():
    """The body is multipart/form-data with a field named audio of content type audio/wav."""
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert seen[0].headers["content-type"].startswith("multipart/form-data")
    body = seen[0].content
    assert b'name="audio"' in body
    assert b"audio/wav" in body


def test_fr3_audio_part_bytes_equal_the_wav():
    """The audio part carries exactly the WAV bytes that were passed in."""
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert QUESTION_WAV in seen[0].content


def test_fr3_only_one_part_is_sent():
    """Exactly one multipart part (audio) is sent."""
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert seen[0].content.count(b"Content-Disposition") == 1


def test_fr3_timeout_is_20_seconds_on_all_phases():
    """The request uses the 20 s client timeout for connect, read, write and pool."""
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert seen[0].extensions["timeout"] == {
        "connect": 20,
        "read": 20,
        "write": 20,
        "pool": 20,
    }


def test_fr3_timeout_follows_config_at_call_time(monkeypatch):
    """The timeout comes from config.QUERY_TIMEOUT_S, read when the query is sent."""
    monkeypatch.setattr(config, "QUERY_TIMEOUT_S", 7)
    seen: list[httpx.Request] = []
    query_with(capture(seen))
    assert set(seen[0].extensions["timeout"].values()) == {7}


def test_fr3_default_query_timeout_is_20_seconds():
    """The default client timeout is 20 s."""
    assert config.QUERY_TIMEOUT_S == 20


def test_fr3_200_wav_returns_the_answer_bytes():
    """A 200 audio/wav response returns the exact answer WAV bytes."""
    assert query_with(answer_handler) == ANSWER_WAV


def test_fr3_content_type_parameters_are_ignored():
    """audio/wav with parameters (charset) is still accepted."""
    handler = fixed_response(
        200, content=ANSWER_WAV, headers={"content-type": "audio/wav; charset=binary"}
    )
    assert query_with(handler) == ANSWER_WAV


def test_fr3_400_raises_query_error_with_status_and_server_text():
    """A 400 raises QueryError that includes the status and the server's error text."""
    handler = fixed_response(400, json={"error": "no speech detected"})
    with pytest.raises(QueryError) as info:
        query_with(handler)
    assert "400" in str(info.value)
    assert "no speech detected" in str(info.value)


def test_fr3_500_raises_query_error_with_status_and_server_text():
    """A 500 raises QueryError that includes the status and the '<stage>: <reason>' text."""
    handler = fixed_response(500, json={"error": "stt: boom"})
    with pytest.raises(QueryError) as info:
        query_with(handler)
    assert "500" in str(info.value)
    assert "stt: boom" in str(info.value)


def test_fr3_500_with_non_json_body_still_raises_with_body_text():
    """A 500 whose body is not JSON raises QueryError that includes the raw body text."""
    handler = fixed_response(500, text="Internal Server Error xyz")
    with pytest.raises(QueryError) as info:
        query_with(handler)
    assert "500" in str(info.value)
    assert "Internal Server Error xyz" in str(info.value)


def test_fr3_200_with_json_content_type_is_a_client_error():
    """A 200 whose content type is not audio/wav raises QueryError."""
    handler = fixed_response(200, json={"hello": "world"})
    with pytest.raises(QueryError):
        query_with(handler)


def test_fr3_200_with_html_content_type_is_a_client_error():
    """A 200 text/html response raises QueryError, not returned as audio."""
    handler = fixed_response(200, html="<html></html>")
    with pytest.raises(QueryError):
        query_with(handler)


def test_fr3_timeout_raises_query_timeout_mentioning_limit():
    """A timeout raises QueryTimeout, which names the 20 s limit."""
    with pytest.raises(QueryTimeout) as info:
        query_with(raising(httpx.ReadTimeout("x")))
    assert type(info.value) is QueryTimeout
    assert "20" in str(info.value)


def test_fr3_refused_connection_raises_server_unreachable_mentioning_url():
    """A refused connection raises ServerUnreachable, which names the server URL."""
    with pytest.raises(ServerUnreachable) as info:
        query_with(raising(httpx.ConnectError("refused")))
    assert type(info.value) is ServerUnreachable
    assert config.SERVER_URL in str(info.value)


def test_fr3_other_http_error_raises_plain_query_error():
    """Any other httpx error raises plain QueryError, not a subclass."""
    with pytest.raises(QueryError) as info:
        query_with(raising(httpx.ReadError("broken")))
    assert type(info.value) is QueryError


def test_fr3_http_status_error_is_plain_query_error():
    """A server error response raises plain QueryError, distinct from timeout and unreachable."""
    with pytest.raises(QueryError) as info:
        query_with(fixed_response(400, json={"error": "bad audio"}))
    assert type(info.value) is QueryError


def test_fr3_error_classes_inherit_from_query_error():
    """QueryTimeout and ServerUnreachable are QueryError subclasses and are distinct."""
    assert issubclass(QueryError, Exception)
    assert issubclass(QueryTimeout, QueryError)
    assert issubclass(ServerUnreachable, QueryError)
    assert not issubclass(QueryTimeout, ServerUnreachable)
    assert not issubclass(ServerUnreachable, QueryTimeout)


# ---- FR-1/FR-2/FR-3: Client state machine (M6-T5). All collaborators are fakes. ----

PTT = keyboard.Key.f9
OTHER = keyboard.Key.space
REC_WAV = b"RECORDED-WAV"
REPLY_WAV = b"ANSWER-WAV"
WAIT_S = 2.0


class FakeRecorder:
    def __init__(self, log: list) -> None:
        self.log = log
        self.on_stop = None

    def start_recording(self) -> bool:
        self.log.append("start_recording")
        return True

    def stop_recording(self) -> bytes:
        self.log.append("stop_recording")
        if self.on_stop:
            self.on_stop()
        return REC_WAV


class FakePlayer:
    def __init__(self, log: list) -> None:
        self.log = log
        self.on_start = None
        self.wav_exc: Exception | None = None
        self.wav_entered = threading.Event()
        self.wav_gate: threading.Event | None = None

    def play_start(self) -> None:
        self.log.append("start")
        if self.on_start:
            self.on_start()

    def play_thinking(self) -> None:
        self.log.append("thinking")

    def play_error(self) -> None:
        self.log.append("error")

    def play_wav(self, data: bytes) -> None:
        self.log.append(("wav", data))
        self.wav_entered.set()
        if self.wav_gate is not None:
            assert self.wav_gate.wait(WAIT_S)
        if self.wav_exc:
            raise self.wav_exc


class FakeSend:
    def __init__(self, log: list, clock) -> None:
        self.log = log
        self.clock = clock
        self.exc: Exception | None = None
        self.answer_at: float | None = None
        self.entered = threading.Event()
        self.gate: threading.Event | None = None

    def __call__(self, wav: bytes) -> bytes:
        self.log.append(("send", wav))
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(WAIT_S)
        if self.exc:
            raise self.exc
        if self.answer_at is not None:
            self.clock.t = self.answer_at
        return REPLY_WAV


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class FakeTimer:
    def __init__(self, interval: float, fn) -> None:
        self.interval = interval
        self.fn = fn
        self.daemon = False
        self.started = 0
        self.cancelled = 0

    def start(self) -> None:
        self.started += 1

    def cancel(self) -> None:
        self.cancelled += 1

    def fire(self) -> None:
        self.fn()


class Deferred:
    """spawn that stores functions so a test can look at the state before they run."""

    def __init__(self) -> None:
        self.pending: list = []

    def __call__(self, fn) -> None:
        self.pending.append(fn)

    def run_all(self) -> None:
        while self.pending:
            self.pending.pop(0)()


class Threaded:
    """spawn that runs fn on a real thread, so a test can block it on an Event."""

    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []

    def __call__(self, fn) -> None:
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        self.threads.append(t)

    def join(self) -> None:
        for t in self.threads:
            t.join(WAIT_S)
            assert not t.is_alive()


class Rig:
    def __init__(self, spawn=None) -> None:
        self.log: list = []
        self.clock = FakeClock()
        self.recorder = FakeRecorder(self.log)
        self.player = FakePlayer(self.log)
        self.send = FakeSend(self.log, self.clock)
        self.timers: list[FakeTimer] = []
        self.client = Client(
            self.recorder,
            self.player,
            send=self.send,
            clock=self.clock,
            spawn=spawn or (lambda fn: fn()),
            timer=self.make_timer,
        )

    def make_timer(self, interval: float, fn) -> FakeTimer:
        t = FakeTimer(interval, fn)
        self.timers.append(t)
        return t

    def press(self, key=PTT) -> None:
        self.client.on_key_press(key)

    def release(self, key=PTT) -> None:
        self.client.on_key_release(key)

    def cycle(self, held: float = 1.0) -> None:
        self.press()
        self.clock.t += held
        self.release()

    def count(self, item) -> int:
        return self.log.count(item)


def returns_promptly(fn) -> None:
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    t.join(WAIT_S)
    assert not t.is_alive(), "key handler blocked"


@pytest.fixture
def rig():
    return Rig()


def test_fr1_client_starts_idle(rig):
    """The client has one state and starts idle."""
    assert rig.client.state == "idle"


def test_fr1_non_ptt_keys_are_ignored(rig):
    """Only the push-to-talk key is handled: other keys do nothing on press or release."""
    rig.press(OTHER)
    rig.release(OTHER)
    assert rig.log == []
    assert rig.client.state == "idle"
    assert rig.timers == []
    rig.press()
    rig.release(OTHER)
    assert rig.client.state == "recording"
    assert rig.count("stop_recording") == 0


def test_fr1_ptt_key_comes_from_config(monkeypatch, rig):
    """The PTT key is read from config.PTT_KEY at call time."""
    assert config.PTT_KEY == "f9"
    monkeypatch.setattr(config, "PTT_KEY", "f8")
    rig.press(PTT)
    assert rig.log == []
    rig.press(keyboard.Key.f8)
    assert rig.client.state == "recording"


def test_fr1_press_starts_recording_and_plays_start_sound_once(rig):
    """A key press plays the start sound once and starts recording."""
    rig.press()
    assert rig.client.state == "recording"
    assert rig.count("start_recording") == 1
    assert rig.count("start") == 1
    assert rig.log.index("start_recording") < rig.log.index("start")


def test_fr1_key_repeat_presses_while_recording_are_ignored(rig):
    """Key-repeat presses while the key is held do not restart or replay anything."""
    rig.press()
    rig.press()
    rig.press()
    assert rig.count("start_recording") == 1
    assert rig.count("start") == 1
    assert len(rig.timers) == 1
    assert rig.client.state == "recording"


def test_fr1_release_without_press_is_ignored(rig):
    """A release with no earlier press does nothing."""
    rig.release()
    assert rig.log == []
    assert rig.client.state == "idle"


def test_fr1_press_ignored_while_waiting():
    """A key press is ignored unless idle: nothing happens in the waiting state."""
    spawn = Deferred()
    rig = Rig(spawn)
    rig.press()
    spawn.run_all()
    rig.release()
    assert rig.client.state == "waiting"
    rig.press()
    assert rig.client.state == "waiting"
    assert rig.count("start_recording") == 1
    assert len(rig.timers) == 1
    assert len(spawn.pending) == 1  # only the query from the release


def test_fr1_press_ignored_while_waiting_for_server():
    """While send() waits for the server the state is waiting and key events return at once."""
    spawn = Threaded()
    rig = Rig(spawn)
    rig.send.gate = threading.Event()
    rig.press()
    spawn.join()
    rig.clock.t = 1.0
    rig.release()
    try:
        assert rig.send.entered.wait(WAIT_S)
        assert rig.client.state == "waiting"
        returns_promptly(rig.press)
        returns_promptly(rig.release)
        assert rig.client.state == "waiting"
        assert rig.count("start_recording") == 1
        assert rig.count("start") == 1
    finally:
        rig.send.gate.set()
        spawn.join()
    assert rig.client.state == "idle"


def test_fr1_press_ignored_while_playing_and_lock_covers_playback():
    """While play_wav runs the state is playing; press and release return promptly and change nothing."""
    spawn = Threaded()
    rig = Rig(spawn)
    rig.player.wav_gate = threading.Event()
    rig.press()
    spawn.join()
    rig.clock.t = 1.0
    rig.release()
    try:
        assert rig.player.wav_entered.wait(WAIT_S)
        assert rig.client.state == "playing"
        before = list(rig.log)
        returns_promptly(rig.press)
        returns_promptly(rig.release)
        assert rig.client.state == "playing"
        assert rig.log == before
        assert len(rig.timers) == 1
    finally:
        rig.player.wav_gate.set()
        spawn.join()
    assert rig.client.state == "idle"
    assert rig.count("start_recording") == 1


def test_fr1_second_press_during_start_sound_is_ignored(rig):
    """A press that arrives while the start sound transition is running has no effect."""
    rig.player.on_start = rig.press
    rig.press()
    assert rig.count("start_recording") == 1
    assert rig.count("start") == 1
    assert len(rig.timers) == 1
    assert rig.client.state == "recording"


def test_fr1_second_press_during_release_transition_is_ignored(rig):
    """A press that arrives while the release is stopping the recording has no effect."""
    rig.press()
    rig.recorder.on_stop = rig.press
    rig.clock.t = 1.0
    rig.release()
    assert rig.count("start_recording") == 1
    assert rig.count("start") == 1
    assert rig.client.state == "idle"
    assert rig.count(("wav", REPLY_WAV)) == 1


def test_fr1_normal_cycle_runs_in_order_and_ends_idle(rig):
    """Press plays the start sound and records; release plays thinking, sends the audio, plays the answer."""
    rig.cycle(held=1.0)
    assert rig.log == [
        "start_recording",
        "start",
        "stop_recording",
        "thinking",
        ("send", REC_WAV),
        ("wav", REPLY_WAV),
    ]
    assert rig.client.state == "idle"


def test_fr1_state_goes_through_waiting_and_playing_in_a_cycle():
    """The state is recording after press, waiting after release, then playing, then idle."""
    spawn = Deferred()
    rig = Rig(spawn)
    states = []
    rig.player.on_start = lambda: states.append(rig.client.state)
    rig.press()
    states.append(rig.client.state)
    spawn.run_all()
    rig.clock.t = 1.0
    rig.release()
    states.append(rig.client.state)
    spawn.run_all()
    assert states == ["recording", "recording", "waiting"]
    assert rig.client.state == "idle"


def test_fr1_two_cycles_in_a_row_both_work(rig):
    """After a finished query the next key press works."""
    rig.cycle()
    rig.cycle()
    assert rig.count("start_recording") == 2
    assert rig.count(("wav", REPLY_WAV)) == 2
    assert rig.client.state == "idle"


def test_fr1_short_recording_sends_nothing_and_plays_error_only(rig):
    """A recording shorter than 0.3 s is discarded: error tone, no thinking sound, no request."""
    assert config.MIN_RECORDING_S == 0.3
    rig.cycle(held=0.2)
    assert not any(isinstance(x, tuple) for x in rig.log)
    assert "thinking" not in rig.log
    assert rig.count("error") == 1
    assert rig.client.state == "idle"


def test_fr1_short_recording_state_is_waiting_then_error_then_idle():
    """After a too-short release the state is waiting, and idle again once the error tone ends."""
    spawn = Deferred()
    rig = Rig(spawn)
    rig.press()
    spawn.run_all()
    rig.clock.t = 0.1
    rig.release()
    assert rig.client.state == "waiting"
    spawn.run_all()
    assert rig.client.state == "idle"
    assert rig.log[-1] == "error"


def test_fr1_recording_of_exactly_min_length_is_sent(rig):
    """A recording held for exactly MIN_RECORDING_S is not discarded."""
    rig.cycle(held=config.MIN_RECORDING_S)
    assert ("send", REC_WAV) in rig.log
    assert "error" not in rig.log


def test_fr1_next_press_works_after_short_recording(rig):
    """After a discarded short recording the next press works."""
    rig.cycle(held=0.1)
    rig.cycle(held=1.0)
    assert ("send", REC_WAV) in rig.log
    assert rig.client.state == "idle"


def test_fr3_latency_line_is_logged_for_a_query(rig, caplog):
    """The time from key release to the start of the answer is logged as 'latency 2.9 s'."""
    rig.press()
    rig.clock.t = 10.0
    rig.send.answer_at = 12.9
    with caplog.at_level(logging.INFO, logger="client_pc.client"):
        rig.release()
    lines = [
        r.getMessage()
        for r in caplog.records
        if r.name == "client_pc.client" and r.levelno == logging.INFO
    ]
    assert lines.count("latency 2.9 s") == 1


def test_fr3_latency_is_logged_before_the_answer_plays(rig, caplog):
    """The latency is measured when the answer starts: it is logged before play_wav is called."""
    seen = []
    original = rig.player.play_wav

    def checking(data):
        seen.append(any("latency" in r.getMessage() for r in caplog.records))
        original(data)

    rig.player.play_wav = checking
    rig.press()
    rig.clock.t = 5.0
    with caplog.at_level(logging.INFO, logger="client_pc.client"):
        rig.release()
    assert seen == [True]


def test_fr3_latency_is_not_logged_for_a_failed_query(rig, caplog):
    """A failed query logs no latency line."""
    rig.send.exc = QueryError("500 stt: boom")
    with caplog.at_level(logging.INFO, logger="client_pc.client"):
        rig.cycle()
    assert not [r for r in caplog.records if "latency" in r.getMessage()]


def test_fr1_short_recording_logs_no_latency(rig, caplog):
    """A discarded short recording logs no latency line."""
    with caplog.at_level(logging.INFO, logger="client_pc.client"):
        rig.cycle(held=0.1)
    assert not [r for r in caplog.records if "latency" in r.getMessage()]


LONG = "x" * 500
FAILURES = [
    ("send", QueryError(LONG)),
    ("send", QueryTimeout(LONG)),
    ("send", ServerUnreachable(LONG)),
    ("play_wav", ValueError(LONG)),
]


@pytest.mark.parametrize(
    ("where", "exc"),
    FAILURES,
    ids=["query_error", "timeout", "unreachable", "play_wav_value_error"],
)
def test_fr3_failure_plays_error_logs_warning_and_next_press_works(
    rig, caplog, where, exc
):
    """Any failure plays the error sound, logs a cut warning, and the next key press works."""
    if where == "send":
        rig.send.exc = exc
    else:
        rig.player.wav_exc = exc
    with caplog.at_level(logging.INFO, logger="client_pc.client"):
        rig.cycle()
    assert rig.count("error") == 1
    assert rig.log[-1] == "error"
    if where == "send":
        assert ("wav", REPLY_WAV) not in rig.log
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "x" * config.ERROR_MAX_CHARS in warnings[0]
    assert "x" * (config.ERROR_MAX_CHARS + 1) not in warnings[0]
    assert rig.client.state == "idle"

    rig.send.exc = None
    rig.player.wav_exc = None
    rig.log.clear()
    rig.cycle()
    assert rig.log[-1] == ("wav", REPLY_WAV)
    assert rig.count("error") == 0
    assert rig.client.state == "idle"


def test_fr3_timeout_failure_is_not_a_crash_in_handler(rig):
    """A QueryTimeout inside the query never propagates out of the key handler."""
    rig.send.exc = QueryTimeout("no answer within 20 s")
    rig.cycle()
    assert rig.client.state == "idle"


def test_fr3_error_max_chars_default():
    """The logged error text is cut to 200 characters by default."""
    assert config.ERROR_MAX_CHARS == 200


def test_fr1_max_record_timer_is_created_started_and_daemon(rig):
    """A press creates one started daemon timer set to MAX_RECORD_S."""
    rig.press()
    assert len(rig.timers) == 1
    timer = rig.timers[0]
    assert timer.interval == config.MAX_RECORD_S == 10
    assert timer.started == 1
    assert timer.daemon is True


def test_fr1_timer_firing_stops_recording_and_sends_query(rig):
    """At the max recording time the recording stops and the query is sent without a key release."""
    rig.press()
    rig.clock.t = 10.0
    rig.timers[0].fire()
    assert rig.count("stop_recording") == 1
    assert ("send", REC_WAV) in rig.log
    assert rig.log[-1] == ("wav", REPLY_WAV)
    assert rig.client.state == "idle"


def test_fr1_release_after_timer_fired_is_ignored(rig):
    """A real key release after the timer already stopped the recording does nothing."""
    rig.press()
    rig.clock.t = 10.0
    rig.timers[0].fire()
    before = list(rig.log)
    rig.release()
    assert rig.log == before
    assert rig.client.state == "idle"


def test_fr1_normal_release_cancels_the_timer(rig):
    """A normal release cancels the max-recording timer."""
    rig.cycle()
    assert rig.timers[0].cancelled >= 1


def test_fr1_each_press_gets_its_own_timer(rig):
    """A second recording gets a fresh timer."""
    rig.cycle()
    rig.cycle()
    assert len(rig.timers) == 2
    assert all(t.started == 1 for t in rig.timers)
