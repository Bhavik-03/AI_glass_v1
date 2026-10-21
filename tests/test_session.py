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


def _normalised(phrase: str) -> str:
    import re

    return " ".join(re.sub(r"[^\w\s]", " ", phrase.lower()).split())


def test_fr31_proposal_phrase_sets_are_frozensets_of_str():
    """PROPOSAL_YES and PROPOSAL_NO are frozensets of str."""
    for phrases in (config.PROPOSAL_YES, config.PROPOSAL_NO):
        assert isinstance(phrases, frozenset)
        assert phrases
        assert all(isinstance(p, str) for p in phrases)


def test_fr31_proposal_phrases_are_normalised():
    """Each phrase is lower case, only word characters and single spaces."""
    for p in config.PROPOSAL_YES | config.PROPOSAL_NO:
        assert p == _normalised(p)
        assert p == p.strip()


def test_fr31_proposal_yes_and_no_are_disjoint():
    """No phrase is both a yes and a no."""
    assert config.PROPOSAL_YES.isdisjoint(config.PROPOSAL_NO)


def test_fr31_proposal_known_phrases_present():
    """yes and yes please are yes phrases; no is a no phrase."""
    assert "yes" in config.PROPOSAL_YES
    assert "yes please" in config.PROPOSAL_YES
    assert "no" in config.PROPOSAL_NO


def test_fr31_no_proposal_by_default():
    """With nothing proposed, proposal() returns None."""
    assert session.proposal(T0) is None


def test_fr31_propose_and_read():
    """propose sets the pending proposal as {kind, slot, value}."""
    session.propose("update", "goal_now", "crack interviews", T0)
    assert session.proposal(T0 + secs(1)) == {
        "kind": "update",
        "slot": "goal_now",
        "value": "crack interviews",
    }


def test_fr31_proposal_read_does_not_consume():
    """Reading the proposal leaves it pending."""
    session.propose("confirm", "goal_now", "v", T0)
    first = session.proposal(T0 + secs(1))
    assert session.proposal(T0 + secs(2)) == first


def test_fr31_second_propose_replaces_first():
    """At most one proposal is pending: a second propose replaces the first."""
    session.propose("update", "goal_now", "a", T0)
    session.propose("confirm", "name", "b", T0 + secs(5))
    assert session.proposal(T0 + secs(6)) == {
        "kind": "confirm",
        "slot": "name",
        "value": "b",
    }


def test_fr31_proposal_returns_a_copy():
    """Mutating the dict from proposal() does not change the session."""
    session.propose("update", "goal_now", "a", T0)
    got = session.proposal(T0 + secs(1))
    got["value"] = "changed"
    got["slot"] = "other"
    assert session.proposal(T0 + secs(2)) == {
        "kind": "update",
        "slot": "goal_now",
        "value": "a",
    }


def test_fr31_proposal_present_just_before_ttl():
    """The proposal is there 119 s after it was asked."""
    session.propose("update", "goal_now", "a", T0)
    assert session.proposal(T0 + secs(119)) is not None


def test_fr31_proposal_gone_at_ttl_and_stays_gone():
    """At 120 s the proposal is None, and stays None."""
    session.propose("update", "goal_now", "a", T0)
    assert session.proposal(T0 + secs(120)) is None
    assert session.proposal(T0 + secs(121)) is None
    assert session.proposal(T0 + secs(1)) is None


def test_fr31_proposal_ttl_follows_config(monkeypatch):
    """The proposal lifetime comes from config.SESSION_TTL_S."""
    monkeypatch.setattr(config, "SESSION_TTL_S", 10)
    session.propose("update", "goal_now", "a", T0)
    assert session.proposal(T0 + secs(9)) is not None
    assert session.proposal(T0 + secs(10)) is None


def test_fr31_second_propose_restarts_the_clock():
    """The 120 s counts from the time the latest proposal was asked."""
    session.propose("update", "goal_now", "a", T0)
    session.propose("update", "goal_now", "b", T0 + secs(100))
    assert session.proposal(T0 + secs(100 + 119)) is not None
    assert session.proposal(T0 + secs(100 + 120)) is None


def test_fr31_end_proposal_clears_it():
    """end_proposal clears the pending proposal."""
    session.propose("update", "goal_now", "a", T0)
    session.end_proposal()
    assert session.proposal(T0 + secs(1)) is None


def test_fr31_end_proposal_with_none_pending_is_safe():
    """end_proposal with nothing pending does not raise, and can be repeated."""
    session.end_proposal()
    session.end_proposal()
    assert session.proposal(T0) is None


def test_fr31_nothing_declined_by_default():
    """With nothing declined, declined(slot) is False."""
    assert session.declined("goal_now", T0) is False


def test_fr31_decline_marks_only_that_slot():
    """Declining one slot does not mark others."""
    session.decline("goal_now")
    assert session.declined("goal_now", T0 + secs(1)) is True
    assert session.declined("name", T0 + secs(1)) is False


def test_fr31_decline_is_idempotent():
    """Declining the same slot twice is safe."""
    session.decline("goal_now")
    session.decline("goal_now")
    assert session.declined("goal_now", T0) is True


def test_fr31_decline_survives_turns_within_ttl():
    """Adding turns within the TTL keeps the declined set."""
    session.add_turn("q0", "a0", T0)
    session.decline("goal_now")
    session.add_turn("q1", "a1", T0 + secs(60))
    session.add_turn("q2", "a2", T0 + secs(110))
    assert session.declined("goal_now", T0 + secs(200)) is True


def test_fr31_declined_clears_when_session_expires():
    """The declined set clears SESSION_TTL_S after the last answer, checked on read."""
    session.add_turn("q", "a", T0)
    session.decline("goal_now")
    assert session.declined("goal_now", T0 + secs(119)) is True
    assert session.declined("goal_now", T0 + secs(120)) is False


def test_fr31_declined_expiry_is_for_good():
    """After expiry is seen, the slot is not declined even for an earlier time."""
    session.add_turn("q", "a", T0)
    session.decline("goal_now")
    assert session.declined("goal_now", T0 + secs(121)) is False
    assert session.declined("goal_now", T0 + secs(122)) is False
    assert session.declined("goal_now", T0 + secs(1)) is False


def test_fr31_new_turn_extends_declined_window():
    """The declined set lives 120 s from the last answer, not the first."""
    session.add_turn("q1", "a1", T0)
    session.decline("goal_now")
    session.add_turn("q2", "a2", T0 + secs(100))
    assert session.declined("goal_now", T0 + secs(200)) is True
    assert session.declined("goal_now", T0 + secs(220)) is False


def test_fr31_reset_drops_proposal_and_declined():
    """reset() drops a pending proposal and the declined set."""
    session.propose("update", "goal_now", "a", T0)
    session.decline("goal_now")
    session.reset()
    assert session.proposal(T0 + secs(1)) is None
    assert session.declined("goal_now", T0 + secs(1)) is False


def test_fr31_proposal_does_not_affect_turns_image_quiz_wipe():
    """A pending proposal and declined set leave turns, image, quiz and wipe untouched."""
    session.add_turn("q", "a", T0, image=IMG)
    session.start_quiz(CONCEPTS, T0)
    session.start_wipe(T0)
    session.propose("update", "goal_now", "a", T0 + secs(1))
    session.decline("name")
    assert session.turns(T0 + secs(2)) == [{"question": "q", "answer": "a"}]
    assert session.image(T0 + secs(2)) == IMG
    assert session.quiz(T0 + secs(2))["index"] == 0
    assert session.pending_wipe(T0 + secs(2)) is True


def test_fr31_turns_quiz_wipe_do_not_clear_proposal_or_declined():
    """Adding turns, starting a quiz or a wipe does not clear the proposal or declined set."""
    session.propose("update", "goal_now", "a", T0)
    session.decline("name")
    session.add_turn("q", "a", T0 + secs(1))
    session.start_quiz(CONCEPTS, T0 + secs(2))
    session.start_wipe(T0 + secs(3))
    session.end_quiz()
    session.end_wipe()
    assert session.proposal(T0 + secs(4)) is not None
    assert session.declined("name", T0 + secs(4)) is True


def test_fr31_session_expiry_does_not_drop_proposal_before_its_own_ttl():
    """Turns expiring does not remove a proposal asked later, while its own 120 s runs."""
    session.add_turn("q", "a", T0)
    session.propose("update", "goal_now", "a", T0 + secs(100))
    assert session.turns(T0 + secs(150)) == []
    assert session.proposal(T0 + secs(150)) is not None


def test_fr31_concurrent_proposal_calls_do_not_raise():
    """propose, proposal, decline and declined are safe under many threads."""
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for _ in range(20):
                session.propose("update", f"slot{i}", "v", T0)
                session.proposal(T0 + secs(1))
                session.decline(f"slot{i}")
                session.declined(f"slot{i}", T0 + secs(1))
                session.end_proposal()
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
