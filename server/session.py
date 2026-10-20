import threading
from datetime import datetime

from server import config

# /query runs in FastAPI's thread pool, so every access holds the lock (FR-21).
_lock = threading.Lock()
_turns: list[dict] = []
_image: tuple[bytes, str] | None = None
_last_answer_at: datetime | None = None
_quiz: dict | None = None
_quiz_asked_at: datetime | None = None
_wipe_asked_at: datetime | None = None


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
    """Clear the session, any running quiz and any pending wipe (FR-22, FR-35)."""
    global _quiz, _quiz_asked_at, _wipe_asked_at
    with _lock:
        _clear()
        _quiz = None
        _quiz_asked_at = None
        _wipe_asked_at = None


def start_wipe(now: datetime) -> None:
    """A wipe is waiting for its confirmation phrase, for SESSION_TTL_S from now (FR-35)."""
    global _wipe_asked_at
    with _lock:
        _wipe_asked_at = now


def pending_wipe(now: datetime) -> bool:
    """Whether a wipe still waits for confirmation; an old one is dropped here (FR-35)."""
    global _wipe_asked_at
    with _lock:
        if (
            _wipe_asked_at is not None
            and (now - _wipe_asked_at).total_seconds() >= config.SESSION_TTL_S
        ):
            _wipe_asked_at = None
        return _wipe_asked_at is not None


def end_wipe() -> None:
    """Clear a pending wipe, whether it was confirmed or cancelled (FR-35)."""
    global _wipe_asked_at
    with _lock:
        _wipe_asked_at = None


def start_quiz(concepts: list[dict], now: datetime) -> None:
    """Start a quiz at the first concept; the wait for its answer starts now (FR-24)."""
    global _quiz, _quiz_asked_at
    with _lock:
        _quiz = {"concepts": list(concepts), "index": 0, "right": 0}
        _quiz_asked_at = now


def quiz(now: datetime) -> dict | None:
    """The running quiz, or None; one waiting QUIZ_ANSWER_WAIT_S for an answer ends quietly
    (FR-24). The session's own expiry does not end it."""
    with _lock:
        _expire_quiz(now)
        return None if _quiz is None else {**_quiz, "concepts": list(_quiz["concepts"])}


def answer_quiz(correct: bool, now: datetime) -> dict:
    """Record the grade and move on. Returns the score and the next concept; after the last
    one `next` is None and the quiz is over (FR-24)."""
    global _quiz, _quiz_asked_at
    with _lock:
        _expire_quiz(now)
        if _quiz is None:
            raise RuntimeError("no quiz is running")
        _quiz["right"] += correct
        _quiz["index"] += 1
        _quiz_asked_at = now
        total = len(_quiz["concepts"])
        score = {"right": _quiz["right"], "total": total, "next": None}
        if _quiz["index"] < total:
            score["next"] = _quiz["concepts"][_quiz["index"]]
        else:
            _quiz = None
            _quiz_asked_at = None
        return score


def end_quiz() -> None:
    """End the quiz; turns and image stay (FR-24)."""
    global _quiz, _quiz_asked_at
    with _lock:
        _quiz = None
        _quiz_asked_at = None


def _expire_quiz(now: datetime) -> None:
    global _quiz, _quiz_asked_at
    if (
        _quiz_asked_at is not None
        and (now - _quiz_asked_at).total_seconds() >= config.QUIZ_ANSWER_WAIT_S
    ):
        _quiz = None
        _quiz_asked_at = None


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
