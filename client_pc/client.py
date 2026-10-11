import array
import io
import logging
import math
import threading
import time
import wave
from collections.abc import Callable, Sequence

import httpx
import sounddevice as sd
from pynput import keyboard

from client_pc import config

log = logging.getLogger(__name__)


class Recorder:
    """Keeps the mic stream open and cuts a recording out of it on key press.

    The stream opens once, because opening it takes about 0.5 s (M6-T1 spike).
    Frames are discarded unless the key is held, apart from a short pre-roll
    that catches speech starting just before the press.
    """

    def __init__(self, stream_factory: Callable | None = None) -> None:
        self._factory = stream_factory or sd.RawInputStream
        self._stream = None
        self._lock = threading.Lock()
        self._pre = bytearray()
        self._rec: bytearray | None = None

    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = self._factory(
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype=config.DTYPE,
            callback=self._callback,
        )
        self._stream.start()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    @property
    def recording(self) -> bool:
        return self._rec is not None

    @property
    def full(self) -> bool:
        with self._lock:
            return self._rec is not None and len(self._rec) >= self._max_bytes()

    def start_recording(self) -> bool:
        """Begin with the pre-roll; False if a recording is already running."""
        with self._lock:
            if self._rec is not None:
                return False
            self._rec = bytearray(self._pre)
            return True

    def stop_recording(self) -> bytes | None:
        """End the recording and return it as a WAV, or None if none was running."""
        with self._lock:
            rec, self._rec = self._rec, None
            self._pre.clear()
        return None if rec is None else self._to_wav(bytes(rec))

    def on_audio(self, frames: bytes) -> None:
        with self._lock:
            if self._rec is None:
                self._pre = (self._pre + frames)[-self._pre_bytes() :]
            else:
                room = self._max_bytes() - len(self._rec)
                self._rec += frames[: max(room, 0)]

    def _callback(self, indata, frames, time, status) -> None:
        if status:
            log.warning("audio input status: %s", status)
        self.on_audio(bytes(indata))

    @staticmethod
    def _pre_bytes() -> int:
        return int(config.PRE_ROLL_S * config.SAMPLE_RATE) * config.SAMPLE_BYTES

    @staticmethod
    def _max_bytes() -> int:
        return config.MAX_RECORD_S * config.SAMPLE_RATE * config.SAMPLE_BYTES

    @staticmethod
    def _to_wav(pcm: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(config.CHANNELS)
            w.setsampwidth(config.SAMPLE_BYTES)
            w.setframerate(config.SAMPLE_RATE)
            w.writeframes(pcm)
        return buf.getvalue()


def make_tone(segments: Sequence[tuple[float, float]]) -> bytes:
    """16-bit mono PCM of sine segments (Hz, s); each fades in and out to avoid clicks."""
    peak = config.TONE_VOLUME * 32767
    fade = int(config.TONE_FADE_S * config.SAMPLE_RATE)
    samples = array.array("h")
    for freq, seconds in segments:
        n = round(seconds * config.SAMPLE_RATE)
        for i in range(n):
            envelope = min(1.0, i / fade, (n - 1 - i) / fade)
            angle = 2 * math.pi * freq * i / config.SAMPLE_RATE
            samples.append(round(peak * envelope * math.sin(angle)))
    return samples.tobytes()


class Player:
    """Plays tones and WAVs through one output stream kept open since client start.

    Opening an output stream takes about 0.4 s (M6-T1 spike), so it opens once.
    """

    def __init__(self, stream_factory: Callable | None = None) -> None:
        self._factory = stream_factory or sd.RawOutputStream
        self._stream = None

    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = self._factory(
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype=config.DTYPE,
        )
        self._stream.start()

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()

    def play_start(self) -> None:
        self._play(make_tone(config.START_TONE))

    def play_thinking(self) -> None:
        self._play(make_tone(config.THINKING_TONE))

    def play_error(self) -> None:
        self._play(make_tone(config.ERROR_TONE))

    def play_wav(self, wav: bytes) -> None:
        with wave.open(io.BytesIO(wav), "rb") as w:
            if (w.getnchannels(), w.getframerate(), w.getsampwidth()) != (
                config.CHANNELS,
                config.SAMPLE_RATE,
                config.SAMPLE_BYTES,
            ):
                raise ValueError("audio must be 16 kHz mono 16-bit")
            self._play(w.readframes(w.getnframes()))

    def _play(self, pcm: bytes) -> None:
        # The silence keeps the last real audio from sitting unplayed in the stream
        # buffer when this returns; FR-15 acks a reminder only after it was heard.
        tail = bytes(
            int(config.PLAYBACK_TAIL_S * config.SAMPLE_RATE) * config.SAMPLE_BYTES
        )
        self._stream.write(pcm + tail)


class QueryError(Exception):
    """The server could not answer a question."""


class QueryTimeout(QueryError):
    pass


class ServerUnreachable(QueryError):
    pass


def send_query(wav: bytes, transport: httpx.BaseTransport | None = None) -> bytes:
    """POST the question to /query and return the answer WAV."""
    try:
        with httpx.Client(
            base_url=config.SERVER_URL,
            timeout=config.QUERY_TIMEOUT_S,
            transport=transport,
        ) as http:
            response = http.post(
                "/query", files={"audio": ("question.wav", wav, "audio/wav")}
            )
    except httpx.TimeoutException as e:
        raise QueryTimeout(f"no answer within {config.QUERY_TIMEOUT_S} s") from e
    except httpx.ConnectError as e:
        raise ServerUnreachable(
            f"cannot reach the server at {config.SERVER_URL}"
        ) from e
    except httpx.HTTPError as e:
        raise QueryError(f"request failed: {e}") from e
    if response.status_code != 200:
        raise QueryError(
            f"server returned {response.status_code}: {_error_text(response)}"
        )
    content_type = (
        response.headers.get("content-type", "").split(";")[0].strip().lower()
    )
    if content_type != "audio/wav":
        raise QueryError(f"expected audio/wav, got {content_type or 'no content type'}")
    return response.content


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json()["error"])
    except (ValueError, KeyError, TypeError):
        return response.text


IDLE, RECORDING, WAITING, PLAYING = "idle", "recording", "waiting", "playing"


def _spawn_thread(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


class Client:
    """Push-to-talk cycle: hold the key, ask, hear the answer.

    The lock covers state changes and every Player call, so two sounds never write
    to the output stream at once. It is not held while waiting for the server.
    Key handlers run on pynput's listener thread, so they test the state first and
    return at once when the client is busy.
    """

    def __init__(
        self,
        recorder: Recorder,
        player: Player,
        send: Callable[[bytes], bytes] = send_query,
        clock: Callable[[], float] = time.monotonic,
        spawn: Callable[[Callable[[], None]], None] = _spawn_thread,
        timer: Callable = threading.Timer,
    ) -> None:
        self._recorder = recorder
        self._player = player
        self._send = send
        self._clock = clock
        self._spawn = spawn
        self._timer_factory = timer
        self._lock = threading.Lock()
        self._timer = None
        self._started = 0.0
        self.state = IDLE

    def on_key_press(self, key) -> None:
        if not self._is_ptt(key) or self.state != IDLE:
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self.state != IDLE:
                return
            self._recorder.start_recording()
            self._started = self._clock()
            self._timer = self._timer_factory(config.MAX_RECORD_S, self._release)
            self._timer.daemon = True
            self._timer.start()
            self.state = RECORDING
        finally:
            self._lock.release()
        self._spawn(self._start_sound)

    def on_key_release(self, key) -> None:
        if self._is_ptt(key):
            self._release()

    def _release(self) -> None:
        t_release = self._clock()
        if self.state != RECORDING:
            return
        with self._lock:
            if self.state != RECORDING:
                return
            self._timer.cancel()
            held = t_release - self._started
            self.state = WAITING
            wav = self._recorder.stop_recording()
        if held < config.MIN_RECORDING_S:
            self._spawn(self._discard)
        else:
            self._spawn(lambda: self._query(wav, t_release))

    def _start_sound(self) -> None:
        with self._lock:
            self._player.play_start()

    def _discard(self) -> None:
        try:
            self._play(self._player.play_error)
        finally:
            self.state = IDLE

    def _query(self, wav: bytes, t_release: float) -> None:
        try:
            with self._lock:
                self._player.play_thinking()
            answer = self._send(wav)
            with self._lock:
                self.state = PLAYING
                log.info("latency %.1f s", self._clock() - t_release)
                self._player.play_wav(answer)
        except Exception as e:  # noqa: BLE001  any failure must end in the error sound
            log.warning("query failed: %s", str(e)[: config.ERROR_MAX_CHARS])
            self._play(self._player.play_error)
        finally:
            self.state = IDLE

    def _play(self, play: Callable[[], None]) -> None:
        with self._lock:
            self.state = PLAYING
            play()

    @staticmethod
    def _is_ptt(key) -> bool:
        return key == getattr(keyboard.Key, config.PTT_KEY)
