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


CONCEPTS = [
    {"name": "LoRA", "summary": "Low-rank fine-tuning.", "status": "new"},
    {"name": "Attention", "summary": "Weights tokens.", "status": "learning"},
    {"name": "Softmax", "summary": "Makes probabilities.", "status": "new"},
]


def test_fr24_answer_wait_is_300_seconds():
    """The wait for a quiz answer is config.QUIZ_ANSWER_WAIT_S = 300 s."""
    assert config.QUIZ_ANSWER_WAIT_S == 300


def test_fr24_no_quiz_by_default():
    """With no quiz started, quiz() returns None."""
    assert session.quiz(T0) is None


def test_fr24_start_quiz_and_read():
    """start_quiz begins at index 0 with 0 right and the given concepts."""
    session.start_quiz(CONCEPTS, T0)
    assert session.quiz(T0 + secs(1)) == {
        "concepts": CONCEPTS,
        "index": 0,
        "right": 0,
    }


def test_fr24_answer_quiz_advances_and_counts_right_and_wrong():
    """answer_quiz moves to the next concept and counts only right answers."""
    session.start_quiz(CONCEPTS, T0)
    res = session.answer_quiz(True, T0 + secs(10))
    assert res == {"right": 1, "total": 3, "next": CONCEPTS[1]}
    assert session.quiz(T0 + secs(11))["index"] == 1
    res = session.answer_quiz(False, T0 + secs(20))
    assert res == {"right": 1, "total": 3, "next": CONCEPTS[2]}
    state = session.quiz(T0 + secs(21))
    assert state["index"] == 2
    assert state["right"] == 1


def test_fr24_last_answer_returns_score_and_clears_quiz():
    """After the last concept, next is None with the score, and the quiz ends."""
    session.start_quiz(CONCEPTS[:2], T0)
    session.answer_quiz(True, T0 + secs(5))
    res = session.answer_quiz(True, T0 + secs(10))
    assert res == {"right": 2, "total": 2, "next": None}
    assert session.quiz(T0 + secs(11)) is None


def test_fr22_session_expiry_does_not_end_quiz():
    """The 120 s session expiry clears turns but not a running quiz."""
    session.add_turn("q", "a", T0)
    session.start_quiz(CONCEPTS, T0)
    later = T0 + secs(200)
    assert session.quiz(later) is not None
    assert session.turns(later) == []


def test_fr24_quiz_running_at_299_s():
    """299 s after the last question the quiz is still running."""
    session.start_quiz(CONCEPTS, T0)
    assert session.quiz(T0 + secs(299)) is not None


def test_fr24_quiz_ends_at_300_s():
    """300 s after the last question the quiz ends quietly."""
    session.start_quiz(CONCEPTS, T0)
    assert session.quiz(T0 + secs(300)) is None
    assert session.quiz(T0 + secs(301)) is None


def test_fr24_answering_restarts_the_wait():
    """A graded answer restarts the 300 s wait from that moment."""
    session.start_quiz(CONCEPTS, T0)
    session.answer_quiz(True, T0 + secs(250))
    assert session.quiz(T0 + secs(250 + 299)) is not None
    assert session.quiz(T0 + secs(250 + 300)) is None


def test_fr24_reset_clears_quiz():
    """reset() also clears a running quiz."""
    session.start_quiz(CONCEPTS, T0)
    session.reset()
    assert session.quiz(T0 + secs(1)) is None


def test_fr24_end_quiz_keeps_turns_and_image():
    """end_quiz clears only the quiz; turns and image stay."""
    session.add_turn("q", "a", T0, image=IMG)
    session.start_quiz(CONCEPTS, T0)
    session.end_quiz()
    assert session.quiz(T0 + secs(1)) is None
    assert session.turns(T0 + secs(1)) == [{"question": "q", "answer": "a"}]
    assert session.image(T0 + secs(1)) == IMG


def test_fr24_answer_quiz_without_quiz_raises():
    """answer_quiz with no running quiz raises RuntimeError."""
    with pytest.raises(RuntimeError):
        session.answer_quiz(True, T0)


def test_fr24_answer_quiz_after_wait_expired_raises():
    """After the 300 s wait ended the quiz, answer_quiz raises RuntimeError."""
    session.start_quiz(CONCEPTS, T0)
    session.quiz(T0 + secs(300))
    with pytest.raises(RuntimeError):
        session.answer_quiz(True, T0 + secs(301))


def test_fr24_quiz_returns_a_copy():
    """Mutating the dict from quiz() does not change the stored quiz."""
    session.start_quiz(CONCEPTS, T0)
    got = session.quiz(T0 + secs(1))
    got["index"] = 2
    got["right"] = 9
    got["concepts"].clear()
    again = session.quiz(T0 + secs(2))
    assert again["index"] == 0
    assert again["right"] == 0
    assert len(again["concepts"]) == 3


def test_fr35_no_wipe_pending_by_default():
    """With no wipe started, pending_wipe() is False."""
    assert session.pending_wipe(T0) is False


def test_fr35_start_wipe_makes_it_pending():
    """start_wipe marks a wipe confirmation as pending."""
    session.start_wipe(T0)
    assert session.pending_wipe(T0 + secs(1)) is True


def test_fr35_pending_just_before_ttl():
    """The wipe is still pending 1 s before SESSION_TTL_S."""
    session.start_wipe(T0)
    assert session.pending_wipe(T0 + secs(config.SESSION_TTL_S - 1)) is True


def test_fr35_not_pending_at_exactly_ttl():
    """At exactly SESSION_TTL_S after the start the wipe has expired (same rule as turns)."""
    session.start_wipe(T0)
    assert session.pending_wipe(T0 + secs(config.SESSION_TTL_S)) is False


def test_fr35_not_pending_after_ttl():
    """1 s after SESSION_TTL_S the wipe has expired."""
    session.start_wipe(T0)
    assert session.pending_wipe(T0 + secs(config.SESSION_TTL_S + 1)) is False


def test_fr35_expiry_clears_the_flag_for_good():
    """An expired check clears the flag: a later check inside a fresh window is still False."""
    session.start_wipe(T0)
    assert session.pending_wipe(T0 + secs(config.SESSION_TTL_S + 1)) is False
    assert session.pending_wipe(T0 + secs(config.SESSION_TTL_S + 2)) is False
    assert session.pending_wipe(T0 + secs(1)) is False


def test_fr35_end_wipe_clears_it():
    """end_wipe clears the pending wipe."""
    session.start_wipe(T0)
    session.end_wipe()
    assert session.pending_wipe(T0 + secs(1)) is False


def test_fr35_end_wipe_with_nothing_pending_is_safe():
    """end_wipe with no wipe pending does not raise."""
    session.end_wipe()
    assert session.pending_wipe(T0) is False


def test_fr35_reset_clears_the_wipe():
    """reset() clears a pending wipe, so it does not survive into the next session."""
    session.start_wipe(T0)
    session.reset()
    assert session.pending_wipe(T0 + secs(1)) is False


def test_fr35_add_turn_and_turns_do_not_clear_the_wipe():
    """add_turn and turns neither set nor clear the pending wipe."""
    session.add_turn("q0", "a0", T0)
    assert session.pending_wipe(T0 + secs(1)) is False
    session.start_wipe(T0 + secs(2))
    session.add_turn("q", "a", T0 + secs(3))
    session.turns(T0 + secs(4))
    assert session.pending_wipe(T0 + secs(5)) is True


def test_fr35_running_quiz_does_not_set_or_clear_the_wipe():
    """A running quiz neither sets nor clears the pending wipe."""
    session.start_quiz(CONCEPTS, T0)
    assert session.pending_wipe(T0 + secs(1)) is False
    session.start_wipe(T0 + secs(2))
    session.answer_quiz(True, T0 + secs(3))
    session.quiz(T0 + secs(4))
    assert session.pending_wipe(T0 + secs(5)) is True


def test_fr35_start_wipe_keeps_turns_image_and_quiz():
    """Starting a wipe leaves existing turns, the image and a running quiz untouched."""
    session.add_turn("q", "a", T0, image=IMG)
    session.start_quiz(CONCEPTS, T0)

    session.start_wipe(T0 + secs(1))

    assert session.turns(T0 + secs(2)) == [{"question": "q", "answer": "a"}]
    assert session.image(T0 + secs(2)) == IMG
    assert session.quiz(T0 + secs(2)) == {
        "concepts": CONCEPTS,
        "index": 0,
        "right": 0,
    }


def test_fr35_second_start_wipe_restarts_the_clock():
    """A second start_wipe restarts the expiry from the new start."""
    session.start_wipe(T0)
    session.start_wipe(T0 + secs(100))
    assert session.pending_wipe(T0 + secs(100 + config.SESSION_TTL_S - 1)) is True
    assert session.pending_wipe(T0 + secs(100 + config.SESSION_TTL_S)) is False
