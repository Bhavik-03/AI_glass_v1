import threading
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from server import config, session

T0 = datetime(2026, 1, 5, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture(autouse=True)
def _clean_session():
    session.reset()
    yield
    session.reset()


def secs(n: float) -> timedelta:
    return timedelta(seconds=n)


def test_fr21_empty_session_has_no_turns():
    """With no turn added, turns() returns an empty list."""
    assert session.turns(T0) == []


def test_fr21_turn_is_returned_as_question_answer_dict():
    """A turn added is returned as {"question", "answer"}."""
    session.add_turn("what is LoRA?", "A fine-tuning method.", T0)
    assert session.turns(T0 + secs(5)) == [
        {"question": "what is LoRA?", "answer": "A fine-tuning method."}
    ]


def test_fr21_turns_are_oldest_first():
    """Turns come back oldest first."""
    session.add_turn("q1", "a1", T0)
    session.add_turn("q2", "a2", T0 + secs(10))
    got = session.turns(T0 + secs(20))
    assert [t["question"] for t in got] == ["q1", "q2"]


def test_fr21_keeps_only_last_five_turns():
    """Only the 5 newest question/answer pairs are kept."""
    for i in range(7):
        session.add_turn(f"q{i}", f"a{i}", T0 + secs(i))
    got = session.turns(T0 + secs(10))
    assert got == [{"question": f"q{i}", "answer": f"a{i}"} for i in range(2, 7)]


def test_fr21_turns_kept_within_ttl():
    """A follow-up 119 s after the last answer still sees the turns."""
    session.add_turn("q", "a", T0)
    assert len(session.turns(T0 + secs(119))) == 1


def test_fr21_turns_gone_after_ttl():
    """121 s after the last answer the session has ended."""
    session.add_turn("q", "a", T0)
    assert session.turns(T0 + secs(121)) == []


def test_fr21_session_ends_at_ttl():
    """The session ends 120 s after the last answer, so at exactly 120 s it is gone."""
    session.add_turn("q", "a", T0)
    assert session.turns(T0 + secs(120)) == []


def test_fr21_expired_session_is_cleared_on_read():
    """An expired read clears the session; a later add_turn starts fresh."""
    session.add_turn("old", "old answer", T0)
    assert session.turns(T0 + secs(200)) == []
    session.add_turn("new", "new answer", T0 + secs(201))
    assert session.turns(T0 + secs(202)) == [
        {"question": "new", "answer": "new answer"}
    ]


def test_fr21_new_turn_extends_window():
    """The 120 s timer counts from the last answer, not the first."""
    session.add_turn("q1", "a1", T0)
    session.add_turn("q2", "a2", T0 + secs(100))
    got = session.turns(T0 + secs(200))  # 200 s after first, 100 s after last
    assert [t["question"] for t in got] == ["q1", "q2"]
    assert session.turns(T0 + secs(100 + 121)) == []


def test_fr21_reset_clears_turns():
    """reset() clears the session."""
    session.add_turn("q", "a", T0)
    session.reset()
    assert session.turns(T0) == []


def test_fr21_reset_with_no_session_is_safe():
    """reset() with no session does not raise."""
    session.reset()
    session.reset()


def test_fr21_max_turns_follows_config(monkeypatch):
    """The turn limit comes from config.SESSION_MAX_TURNS."""
    monkeypatch.setattr(config, "SESSION_MAX_TURNS", 2)
    for i in range(4):
        session.add_turn(f"q{i}", f"a{i}", T0 + secs(i))
    got = session.turns(T0 + secs(5))
    assert [t["question"] for t in got] == ["q2", "q3"]


def test_fr21_ttl_follows_config(monkeypatch):
    """The expiry comes from config.SESSION_TTL_S."""
    monkeypatch.setattr(config, "SESSION_TTL_S", 10)
    session.add_turn("q", "a", T0)
    assert len(session.turns(T0 + secs(9))) == 1
    assert session.turns(T0 + secs(11)) == []


IMG = (b"\xff\xd8jpeg-bytes", "image/jpeg")
IMG2 = (b"\x89PNGpng-bytes", "image/png")


def test_fr21_no_image_saved_returns_none():
    """With no image saved, image() returns None."""
    session.add_turn("q", "a", T0)
    assert session.image(T0 + secs(5)) is None


def test_fr21_image_empty_session_returns_none():
    """With no turns at all, image() returns None."""
    assert session.image(T0) is None


def test_fr21_image_is_saved_with_turn():
    """The most recent image (bytes and type) is kept with the turn."""
    session.add_turn("q", "a", T0, image=IMG)
    assert session.image(T0 + secs(5)) == IMG


def test_fr21_text_follow_up_keeps_earlier_image():
    """A later turn without an image keeps the earlier screenshot."""
    session.add_turn("q1", "a1", T0, image=IMG)
    session.add_turn("q2", "a2", T0 + secs(10))
    assert session.image(T0 + secs(20)) == IMG


def test_fr21_new_image_replaces_old_image():
    """A later turn with a new image replaces the saved one."""
    session.add_turn("q1", "a1", T0, image=IMG)
    session.add_turn("q2", "a2", T0 + secs(10), image=IMG2)
    assert session.image(T0 + secs(20)) == IMG2


def test_fr21_image_kept_119s_after_last_answer():
    """The image is still there 119 s after the last answer."""
    session.add_turn("q", "a", T0, image=IMG)
    assert session.image(T0 + secs(119)) == IMG


def test_fr21_image_gone_at_120s():
    """The image ends with the session at 120 s."""
    session.add_turn("q", "a", T0, image=IMG)
    assert session.image(T0 + secs(120)) is None


def test_fr21_image_gone_at_121s():
    """The image is gone 121 s after the last answer."""
    session.add_turn("q", "a", T0, image=IMG)
    assert session.image(T0 + secs(121)) is None


def test_fr21_text_turn_extends_image_life():
    """The timer counts from the last answer, so a text turn extends the image."""
    session.add_turn("q1", "a1", T0, image=IMG)
    session.add_turn("q2", "a2", T0 + secs(100))
    assert session.image(T0 + secs(200)) == IMG
    assert session.image(T0 + secs(100 + 120)) is None


def test_fr21_expired_image_not_resurrected():
    """After expiry, a new turn without an image has no image."""
    session.add_turn("q1", "a1", T0, image=IMG)
    session.add_turn("q2", "a2", T0 + secs(200))
    assert session.image(T0 + secs(201)) is None


def test_fr21_expired_image_not_resurrected_after_read():
    """An expired read clears the image; a later text turn does not bring it back."""
    session.add_turn("q1", "a1", T0, image=IMG)
    assert session.image(T0 + secs(150)) is None
    session.add_turn("q2", "a2", T0 + secs(151))
    assert session.image(T0 + secs(152)) is None


def test_fr21_reset_clears_image():
    """reset() clears the image."""
    session.add_turn("q", "a", T0, image=IMG)
    session.reset()
    assert session.image(T0 + secs(1)) is None


def test_fr21_add_turn_without_image_argument_still_works():
    """Existing 3-argument add_turn calls still work and save no image."""
    session.add_turn("q", "a", T0)
    assert session.turns(T0 + secs(1)) == [{"question": "q", "answer": "a"}]
    assert session.image(T0 + secs(1)) is None


def test_fr21_concurrent_add_turn_keeps_max_turns():
    """add_turn is safe under many threads: exactly the max turns remain."""
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            session.add_turn(f"q{i}", f"a{i}", T0)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(session.turns(T0 + secs(1))) == config.SESSION_MAX_TURNS
