"""Tests for eval/record.py, the eval clip recorder (FR-1, FR-4). Fake recorder, player and input."""

import array
import io
import json
import wave

import pytest

from client_pc.client import Recorder
from eval import config as eval_config
from eval import record


def make_wav(value: int, samples: int = 1600) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(array.array("h", [value] * samples).tobytes())
    return buf.getvalue()


class FakeRecorder:
    def __init__(self, takes: list[bytes | None]) -> None:
        self.takes = list(takes)
        self.starts = 0
        self.stops = 0
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1

    def start_recording(self) -> bool:
        self.starts += 1
        return True

    def stop_recording(self) -> bytes | None:
        self.stops += 1
        return self.takes.pop(0)

    def close(self) -> None:
        self.closed += 1


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.opened = 0
        self.closed = 0

    def open(self) -> None:
        self.opened += 1

    def play_wav(self, wav: bytes) -> None:
        self.played.append(wav)

    def close(self) -> None:
        self.closed += 1


class FakeInput:
    """Scripted answers for ask(); records the prompts."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str = "") -> str:
        self.prompts.append(prompt)
        return self.answers.pop(0)


@pytest.fixture
def clip_dir(tmp_path, monkeypatch):
    d = tmp_path / "eval"
    monkeypatch.setattr(eval_config, "CLIP_DIR", d)
    return d


def q(qid: str, spoken: str = "what time is it") -> dict:
    return {"id": qid, "spoken": spoken}


def run_one(question, takes, answers, say=None):
    rec, ply, ask = FakeRecorder(takes), FakePlayer(), FakeInput(answers)
    out: list[str] = []
    result = record.record_question(question, rec, ply, ask=ask, say=say or out.append)
    return result, rec, ply, ask, out


def test_fr4_clip_path_is_clip_dir_slash_id_wav(clip_dir):
    """A clip is saved as data/eval/<id>.wav (CLIP_DIR read at call time)."""
    assert record.clip_path("q07") == clip_dir / "q07.wav"


def test_fr4_question_id_and_spoken_text_are_shown(clip_dir):
    """The tool shows the question id and its spoken text."""
    _, _, _, _, out = run_one(
        q("q07", "remind me at five"), [make_wav(1)], ["", "", ""]
    )
    shown = "\n".join(out)
    assert "q07" in shown
    assert "remind me at five" in shown


def test_fr4_enter_keeps_and_saves_the_clip(clip_dir):
    """ENTER at review saves the clip and returns True; the dir is created if missing."""
    wav = make_wav(5)
    assert not clip_dir.exists()
    result, rec, _, _, _ = run_one(q("q01"), [wav], ["", "", ""])
    assert result is True
    assert (clip_dir / "q01.wav").read_bytes() == wav
    assert rec.starts == 1 and rec.stops == 1


def test_fr4_nothing_is_written_before_review_answer(clip_dir):
    """The file is only written when the take is kept, not when recording stops."""
    seen: list[bool] = []

    def ask(prompt: str = "") -> str:
        seen.append((clip_dir / "q01.wav").exists())
        return "" if len(seen) < 3 else "q"

    record.record_question(
        q("q01"), FakeRecorder([make_wav(1)]), FakePlayer(), ask=ask, say=lambda s: None
    )
    assert seen == [False, False, False]
    assert not (clip_dir / "q01.wav").exists()


def test_fr4_recording_waits_for_enter_to_start_and_to_stop(clip_dir):
    """Recording starts after the first ENTER and stops after the second."""
    events: list[str] = []

    class Rec(FakeRecorder):
        def start_recording(self):
            events.append("start")
            return super().start_recording()

        def stop_recording(self):
            events.append("stop")
            return super().stop_recording()

    answers = iter(["", "", ""])

    def ask(prompt: str = "") -> str:
        events.append("ask")
        return next(answers)

    record.record_question(
        q("q01"), Rec([make_wav(1)]), FakePlayer(), ask=ask, say=lambda s: None
    )
    assert events[:4] == ["ask", "start", "ask", "stop"]


def test_fr4_redo_records_twice_and_saves_second_take(clip_dir):
    """'r' discards the take and starts over; the second take is the one saved."""
    first, second = make_wav(1), make_wav(2)
    result, rec, _, _, _ = run_one(q("q01"), [first, second], ["", "", "r", "", "", ""])
    assert result is True
    assert rec.starts == 2
    assert (clip_dir / "q01.wav").read_bytes() == second


def test_fr4_redo_alone_writes_nothing(clip_dir):
    """After 'r' and before the next keep, no file exists."""
    rec, ply = FakeRecorder([make_wav(1), make_wav(2)]), FakePlayer()
    answers = iter(["", "", "r", "", "", "q"])
    record.record_question(
        q("q01"), rec, ply, ask=lambda p="": next(answers), say=lambda s: None
    )
    assert not (clip_dir / "q01.wav").exists()


def test_fr4_playback_plays_current_take_and_does_not_save(clip_dir):
    """'p' plays the bytes of the current take, asks again, and saves nothing by itself."""
    wav = make_wav(3)
    result, _, ply, _, _ = run_one(q("q01"), [wav], ["", "", "p", "q"])
    assert result is False
    assert ply.played == [wav]
    assert not (clip_dir / "q01.wav").exists()


def test_fr4_playback_then_enter_saves_the_played_take(clip_dir):
    """After playing back, ENTER keeps the same take."""
    wav = make_wav(3)
    result, _, ply, _, _ = run_one(q("q01"), [wav], ["", "", "p", "p", ""])
    assert result is True
    assert ply.played == [wav, wav]
    assert (clip_dir / "q01.wav").read_bytes() == wav


def test_fr4_review_input_is_stripped_and_lowercased(clip_dir):
    """Review answers like ' P ' and 'Q' work."""
    wav = make_wav(3)
    result, _, ply, _, _ = run_one(q("q01"), [wav], ["", "", " P ", "Q"])
    assert result is False
    assert ply.played == [wav]


def test_fr4_quit_saves_nothing_and_returns_false(clip_dir):
    """'q' discards the current clip, writes nothing and returns False."""
    result, _, _, _, _ = run_one(q("q01"), [make_wav(1)], ["", "", "q"])
    assert result is False
    assert not (clip_dir / "q01.wav").exists()


def test_fr1_no_recording_reports_error_and_starts_over(clip_dir):
    """If stop_recording returns None, an error is shown and the question restarts."""
    wav = make_wav(4)
    result, rec, _, _, out = run_one(q("q01"), [None, wav], ["", "", "", "", ""])
    assert result is True
    assert rec.starts == 2
    assert (clip_dir / "q01.wav").read_bytes() == wav
    assert len(out) >= 2  # question shown again plus an error message


def test_fr4_pending_skips_existing_clips_and_keeps_order(clip_dir):
    """Questions whose clip already exists are skipped; order is kept."""
    clip_dir.mkdir(parents=True)
    (clip_dir / "q02.wav").write_bytes(make_wav(1))
    (clip_dir / "q04.wav").write_bytes(make_wav(1))
    qs = [q("q01"), q("q02"), q("q03"), q("q04"), q("q05")]
    assert [x["id"] for x in record.pending(qs)] == ["q01", "q03", "q05"]


def test_fr4_pending_with_missing_clip_dir_returns_all(clip_dir):
    """With no clip folder yet, every question is pending."""
    qs = [q("q01"), q("q02")]
    assert record.pending(qs) == qs


@pytest.fixture
def main_env(clip_dir, tmp_path, monkeypatch):
    qs = [q("q01"), q("q02"), q("q03")]
    path = tmp_path / "questions.json"
    path.write_text(json.dumps(qs), encoding="utf-8")
    monkeypatch.setattr(eval_config, "QUESTIONS_PATH", path)
    made: dict = {}

    def install(takes, answers):
        made["rec"] = FakeRecorder(takes)
        made["ply"] = FakePlayer()
        made["ask"] = FakeInput(answers)
        monkeypatch.setattr(record, "Recorder", lambda: made["rec"])
        monkeypatch.setattr(record, "Player", lambda: made["ply"])
        monkeypatch.setattr("builtins.input", made["ask"])
        return made

    return install


def test_fr4_main_records_all_pending_in_order(main_env, clip_dir, capsys):
    """main records every question in order, saves each clip and shows 'n of N' progress."""
    wavs = [make_wav(1), make_wav(2), make_wav(3)]
    made = main_env(wavs, ["", "", ""] * 3)
    record.main()
    for i, qid in enumerate(["q01", "q02", "q03"]):
        assert (clip_dir / f"{qid}.wav").read_bytes() == wavs[i]
    assert made["rec"].opened == 1 and made["ply"].opened == 1
    assert made["rec"].closed >= 1 and made["ply"].closed >= 1
    out = capsys.readouterr().out
    assert "1 of 3" in out and "3 of 3" in out


def test_fr4_restart_after_stopping_halfway_records_only_the_rest(
    main_env, clip_dir, capsys
):
    """Quit on the second question, restart: only the unsaved questions are recorded."""
    w1, w2, w3 = make_wav(1), make_wav(2), make_wav(3)
    made = main_env([w1, w2], ["", "", "", "", "", "q"])
    record.main()
    assert sorted(p.name for p in clip_dir.glob("*.wav")) == ["q01.wav"]
    assert made["rec"].closed >= 1 and made["ply"].closed >= 1

    made = main_env([w2, w3], ["", "", "", "", "", ""])
    record.main()
    assert made["rec"].starts == 2
    assert (clip_dir / "q01.wav").read_bytes() == w1
    assert (clip_dir / "q02.wav").read_bytes() == w2
    assert (clip_dir / "q03.wav").read_bytes() == w3
    assert "2 of 2" in capsys.readouterr().out


def test_fr4_main_stops_at_first_quit(main_env, clip_dir):
    """main stops asking questions after 'q' and closes recorder and player."""
    made = main_env([make_wav(1)], ["", "", "q"])
    record.main()
    assert made["rec"].starts == 1
    assert not list(clip_dir.glob("*.wav")) if clip_dir.exists() else True
    assert made["rec"].closed >= 1 and made["ply"].closed >= 1


def test_fr4_main_closes_both_when_an_error_is_raised(main_env):
    """Recorder and player are closed even if input fails (Ctrl+C)."""
    made = main_env([make_wav(1)], [])
    made["ask"].answers = []  # pop raises IndexError on first ask
    with pytest.raises(IndexError):
        record.main()
    assert made["rec"].closed >= 1 and made["ply"].closed >= 1


def test_fr4_main_with_everything_recorded_does_nothing(main_env, clip_dir, capsys):
    """When all clips exist, main says so and opens no recorder or player."""
    clip_dir.mkdir(parents=True)
    for qid in ("q01", "q02", "q03"):
        (clip_dir / f"{qid}.wav").write_bytes(make_wav(1))
    made = main_env([], [])
    record.main()
    assert made["rec"].starts == 0
    assert made["ask"].prompts == []
    assert "3" in capsys.readouterr().out


def test_fr1_saved_clip_from_real_recorder_is_16khz_mono_16bit(clip_dir):
    """A clip made by the real Recorder is saved unchanged and is 16 kHz mono 16-bit."""

    class MicRecorder:
        """Wraps a real Recorder; the fake mic feeds audio when recording starts."""

        def __init__(self) -> None:
            self.rec = Recorder(stream_factory=lambda **kw: None)

        def start_recording(self) -> bool:
            ok = self.rec.start_recording()
            self.rec.on_audio(array.array("h", [9] * 1600).tobytes())
            return ok

        def stop_recording(self) -> bytes | None:
            self.rec.on_audio(array.array("h", [9] * 1600).tobytes())
            self.wav = self.rec.stop_recording()
            return self.wav

    mic = MicRecorder()
    answers = iter(["", "", ""])
    assert record.record_question(
        q("q01"), mic, FakePlayer(), ask=lambda p="": next(answers), say=lambda s: None
    )
    saved = (clip_dir / "q01.wav").read_bytes()
    assert saved == mic.wav
    with wave.open(io.BytesIO(saved), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() > 0
