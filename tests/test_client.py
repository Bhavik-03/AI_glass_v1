"""Recorder tests for the PC client (FR-1). Fake mic: no sound device is used."""

import array
import io
import math
import wave
from itertools import pairwise

import httpx
import pytest

from client_pc import config
from client_pc.client import (
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
