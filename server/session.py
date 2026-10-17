import threading
from datetime import datetime

from server import config

# /query runs in FastAPI's thread pool, so every access holds the lock (FR-21).
_lock = threading.Lock()
_turns: list[dict] = []
_image: tuple[bytes, str] | None = None
_last_answer_at: datetime | None = None


def add_turn(
    question: str, answer: str, now: datetime, image: tuple[bytes, str] | None = None
) -> None:
    """Keep a finished turn and any new image; the session lasts SESSION_TTL_S from this
    answer (FR-21)."""
    global _image, _last_answer_at
    with _lock:
        _expire(now)
        _turns.append({"question": question, "answer": answer})
        del _turns[: -config.SESSION_MAX_TURNS]
        # A text follow-up keeps the earlier screenshot as the most recent image.
        if image is not None:
            _image = image
        _last_answer_at = now


def turns(now: datetime) -> list[dict]:
    """The kept turns, oldest first; an expired session is cleared here (FR-21)."""
    with _lock:
        _expire(now)
        return [dict(t) for t in _turns]


def image(now: datetime) -> tuple[bytes, str] | None:
    """The most recent image as (bytes, MIME type), or None (FR-21)."""
    with _lock:
        _expire(now)
        return _image


def reset() -> None:
    """Clear the session (FR-22)."""
    with _lock:
        _clear()


def _expire(now: datetime) -> None:
    if (
        _last_answer_at is not None
        and (now - _last_answer_at).total_seconds() >= config.SESSION_TTL_S
    ):
        _clear()


def _clear() -> None:
    global _image, _last_answer_at
    _turns.clear()
    _image = None
    _last_answer_at = None
