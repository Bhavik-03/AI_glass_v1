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
_proposal: dict | None = None
_proposal_asked_at: datetime | None = None
_declined: set[str] = set()
_stale_noted = False
_setup: dict | None = None
_setup_asked_at: datetime | None = None
_setup_stopped = False


def add_turn(
    question: str,
    answer: str,
    now: datetime,
    image: tuple[bytes, str] | None = None,
    stale_noted: bool = False,
) -> None:
    """Keep a finished turn and any new image; the session lasts SESSION_TTL_S from this
    answer (FR-21). stale_noted marks that the stale-goal line was spoken in it (FR-30)."""
    global _image, _last_answer_at, _stale_noted
    with _lock:
        _expire(now)
        _turns.append({"question": question, "answer": answer})
        del _turns[: -config.SESSION_MAX_TURNS]
        # A text follow-up keeps the earlier screenshot as the most recent image.
        if image is not None:
            _image = image
        _last_answer_at = now
        _stale_noted = _stale_noted or stale_noted


def stale_noted(now: datetime) -> bool:
    """Whether the stale-goal line was already said in this session (FR-30)."""
    with _lock:
        _expire(now)
        return _stale_noted


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
    """Clear the session, any running quiz, pending wipe and pending proposal
    (FR-22, FR-35, FR-31)."""
    global _quiz, _quiz_asked_at, _wipe_asked_at, _proposal, _proposal_asked_at
    global _setup, _setup_asked_at, _setup_stopped
    with _lock:
        _clear()
        _quiz = None
        _quiz_asked_at = None
        _wipe_asked_at = None
        _proposal = None
        _proposal_asked_at = None
        _setup = None
        _setup_asked_at = None
        _setup_stopped = False


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


def propose(kind: str, slot: str, value: str, now: datetime) -> None:
    """Hold one profile proposal, kind "update" or "confirm", waiting for a yes or a no
    for SESSION_TTL_S from now; a new one replaces it (FR-31)."""
    global _proposal, _proposal_asked_at
    with _lock:
        _proposal = {"kind": kind, "slot": slot, "value": value}
        _proposal_asked_at = now


def proposal(now: datetime) -> dict | None:
    """The pending proposal, or None; an old one is dropped here (FR-31)."""
    global _proposal, _proposal_asked_at
    with _lock:
        if (
            _proposal_asked_at is not None
            and (now - _proposal_asked_at).total_seconds() >= config.SESSION_TTL_S
        ):
            _proposal = None
            _proposal_asked_at = None
        return None if _proposal is None else dict(_proposal)


def end_proposal() -> None:
    """Clear the pending proposal, whether it was answered or dropped (FR-31)."""
    global _proposal, _proposal_asked_at
    with _lock:
        _proposal = None
        _proposal_asked_at = None


def decline(slot: str) -> None:
    """Remember that the user said no to a proposal for this slot, for this session
    (FR-31)."""
    with _lock:
        _declined.add(slot)


def declined(slot: str, now: datetime) -> bool:
    """Whether the user declined a proposal for this slot in this session (FR-31)."""
    with _lock:
        _expire(now)
        return slot in _declined


def start_setup(slots: list[str], now: datetime) -> None:
    """Start asking the given profile slots in order; the wait for the first answer starts
    now (FR-29)."""
    global _setup, _setup_asked_at
    with _lock:
        _setup = {"slots": list(slots), "index": 0}
        _setup_asked_at = now


def setup(now: datetime) -> dict | None:
    """The running setup, or None; one waiting SETUP_ANSWER_WAIT_S for an answer ends
    quietly (FR-29). The session's own expiry does not end it."""
    with _lock:
        _expire_setup(now)
        return None if _setup is None else {**_setup, "slots": list(_setup["slots"])}


def advance_setup(now: datetime) -> str | None:
    """Move to the next slot and return it; after the last one setup is over and the
    result is None (FR-29)."""
    global _setup, _setup_asked_at
    with _lock:
        _expire_setup(now)
        if _setup is None:
            return None
        _setup["index"] += 1
        _setup_asked_at = now
        if _setup["index"] < len(_setup["slots"]):
            return _setup["slots"][_setup["index"]]
        _setup = None
        _setup_asked_at = None
        return None


def end_setup() -> None:
    """End setup; the answers already written stay (FR-29)."""
    global _setup, _setup_asked_at
    with _lock:
        _setup = None
        _setup_asked_at = None


def stop_setup() -> None:
    """End setup because the user said to stop; it does not restart until the server does
    (FR-29)."""
    global _setup, _setup_asked_at, _setup_stopped
    with _lock:
        _setup = None
        _setup_asked_at = None
        _setup_stopped = True


def setup_stopped() -> bool:
    """Whether the user stopped setup during this server run (FR-29)."""
    with _lock:
        return _setup_stopped


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


def _expire_setup(now: datetime) -> None:
    global _setup, _setup_asked_at
    if (
        _setup_asked_at is not None
        and (now - _setup_asked_at).total_seconds() >= config.SETUP_ANSWER_WAIT_S
    ):
        _setup = None
        _setup_asked_at = None


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
    global _image, _last_answer_at, _stale_noted
    _stale_noted = False
    _turns.clear()
    _declined.clear()
    _image = None
    _last_answer_at = None
