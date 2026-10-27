import io
import logging
import re
import time
import wave
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, File, Response, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from server import config, llm, logger, profile, session, store, stt, tools, tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    profile.load()
    stt.load()
    tts.load()
    yield


app = FastAPI(lifespan=lifespan)


class StageFailed(Exception):
    def __init__(self, stage: str, reason: str, tool_calls: list[dict]) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
        self.tool_calls = tool_calls


def now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


def _reason(error: Exception) -> str:
    """Short error text for the client: keys removed first, so a cut can't leave part of one."""
    text = str(error) or type(error).__name__
    for key in (config.GEMINI_API_KEY, config.TAVILY_API_KEY):
        if key:
            text = text.replace(key, "[redacted]")
    return text[: config.ERROR_MAX_CHARS]


def run_stage(name: str, timings: dict, fn, *args):
    t0 = time.perf_counter()
    try:
        return fn(*args)
    except Exception as e:
        # llm.ask attaches the tool calls made before it failed (FR-17).
        raise StageFailed(name, _reason(e), getattr(e, "tool_calls", [])) from e
    finally:
        timings[name] = round((time.perf_counter() - t0) * 1000)


def _audio_problem(data: bytes | None) -> str | None:
    """Return why the upload can't be used, or None if it is a usable 16 kHz mono 16-bit WAV."""
    if data is None:
        return "audio missing"
    if not data:
        return "audio empty"
    try:
        with wave.open(io.BytesIO(data)) as w:
            frames = w.getnframes()
            wav_format = (w.getnchannels(), w.getsampwidth(), w.getframerate())
    except (wave.Error, EOFError):
        return "audio is not a readable WAV"
    if frames == 0:
        return "audio empty"
    if wav_format != (1, 2, config.SAMPLE_RATE):
        return "audio must be 16 kHz mono 16-bit"
    return None


# The formats the API contract allows, by Pillow format name.
_IMAGE_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png"}


def _image_type(data: bytes) -> str | None:
    """MIME type of a readable JPEG or PNG, else None; taken from the content, not the upload."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            # load() decodes every pixel, so a truncated file fails here, not in Gemini.
            img.load()
            return _IMAGE_TYPES.get(img.format)
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        return None


def _concept(tool_calls: list[dict]) -> str | None:
    """The concept an ok log_concept call stored in this query, even if a later stage failed."""
    for call in tool_calls:
        if call["name"] == "log_concept" and call["status"] == "ok":
            return call["args"]["name"]
    return None


def _memories_used(tool_calls: list[dict]) -> int:
    """How many stored memories the tool results sent to Gemini in this query (FR-17)."""
    return sum(call.get("memories", 0) for call in tool_calls)


def _error(status_code: int, message: str, record: dict) -> JSONResponse:
    record["error"] = message
    return JSONResponse(status_code=status_code, content={"error": message})


def _normalised(transcript: str) -> str:
    """Lower case, punctuation removed, single spaces: the form phrases are matched in."""
    return " ".join(re.sub(r"[^\w\s]", "", transcript.lower()).split())


def _is_stop(transcript: str) -> bool:
    """Whether the transcript says the stop phrase, ignoring case and punctuation (FR-24)."""
    return config.QUIZ_STOP_PHRASE in _normalised(transcript)


def _wipe_request(record: dict, asked_at: datetime) -> Response:
    """Ask back for the confirmation phrase; nothing is deleted yet (FR-35)."""
    record["answer"] = f'Say "{config.WIPE_CONFIRM_PHRASE}" to wipe all your memories.'
    wav = run_stage("tts", record["timings_ms"], tts.synthesize, record["answer"])
    # Pending only after the question was spoken, so a failure leaves nothing waiting.
    session.start_wipe(asked_at)
    return Response(content=wav, media_type="audio/wav")


def _wipe_confirm(record: dict) -> Response:
    """The turn after a wipe request: the exact phrase wipes, anything else cancels. The
    wipe happens only after the answer is spoken, so a failure can be retried (FR-35)."""
    timings = record["timings_ms"]
    confirmed = _normalised(record["question"]) == config.WIPE_CONFIRM_PHRASE
    if confirmed:
        count = store.count_memories()
        record["answer"] = f"Wiped {count} {'memory' if count == 1 else 'memories'}."
    else:
        record["answer"] = "Cancelled. Nothing was deleted."
    wav = run_stage("tts", timings, tts.synthesize, record["answer"])
    if confirmed:
        store.wipe_memories()
    session.end_wipe()
    return Response(content=wav, media_type="audio/wav")


def _quiz_answer(record: dict, quiz: dict, asked_at: datetime) -> Response:
    """Grade the transcript as the answer to the current quiz question and speak the
    feedback plus the next question or the score (FR-24)."""
    timings = record["timings_ms"]
    if _is_stop(record["question"]):
        record["answer"] = "Quiz stopped."
        wav = run_stage("tts", timings, tts.synthesize, record["answer"])
        session.end_quiz()
        return Response(content=wav, media_type="audio/wav")
    concepts, index = quiz["concepts"], quiz["index"]
    concept = concepts[index]
    graded = run_stage(
        "llm",
        timings,
        llm.grade,
        concept["name"],
        concept["summary"],
        record["question"],
    )
    if index + 1 < len(concepts):
        follow = tools.quiz_question(concepts[index + 1]["name"])
    else:
        right = quiz["right"] + graded["correct"]
        follow = tools.quiz_score_text(right, len(concepts))
    record["answer"] = f"{graded['feedback']} {follow}"
    wav = run_stage("tts", timings, tts.synthesize, record["answer"])
    # The quiz moves on only after the answer is spoken, so a failure repeats the question.
    store.set_quiz_result(
        concept["name"], graded["correct"], asked_at.isoformat(timespec="seconds")
    )
    session.answer_quiz(graded["correct"], asked_at)
    return Response(content=wav, media_type="audio/wav")


def _setup_slots() -> list[str]:
    """The setup slots still unanswered, in setup order; slots the schema lacks are skipped."""
    known = {slot["name"] for slot in profile.slots()}
    values = profile.values()
    return [
        name
        for name in config.SETUP_SLOTS
        if name in known and not values.get(name, "").strip()
    ]


def _setup_question(slot: str) -> str:
    return next(s["question"] for s in profile.slots() if s["name"] == slot)


def _setup_start(record: dict, slots: list[str], asked_at: datetime) -> Response:
    """Answer the first query of a setup with the first question, not a normal answer
    (FR-29)."""
    record["answer"] = tools.setup_prompt(_setup_question(slots[0]))
    wav = run_stage("tts", record["timings_ms"], tts.synthesize, record["answer"])
    # Running only after the question was spoken, so a failure leaves no setup behind.
    session.start_setup(slots, asked_at)
    return Response(content=wav, media_type="audio/wav")


def _setup_answer(record: dict, setup: dict, asked_at: datetime) -> Response:
    """The transcript is the answer to the current slot, written and dated today; then the
    next question or the end. "stop setup" keeps what was answered (FR-29)."""
    timings = record["timings_ms"]
    if re.search(config.SETUP_STOP_PATTERN, _normalised(record["question"])):
        record["answer"] = tools.SETUP_STOPPED
        wav = run_stage("tts", timings, tts.synthesize, record["answer"])
        session.stop_setup()
        return Response(content=wav, media_type="audio/wav")
    slots, index = setup["slots"], setup["index"]
    try:
        profile.write(slots[index], record["question"].strip(), asked_at.date())
    except profile.ProfileError as e:
        record["answer"] = tools.setup_refusal_text(
            _reason(e), _setup_question(slots[index])
        )
        wav = run_stage("tts", timings, tts.synthesize, record["answer"])
        return Response(content=wav, media_type="audio/wav")
    next_question = (
        _setup_question(slots[index + 1]) if index + 1 < len(slots) else None
    )
    record["answer"] = tools.setup_noted(profile.values()[slots[index]], next_question)
    wav = run_stage("tts", timings, tts.synthesize, record["answer"])
    # Moving on only after the answer was spoken, so a failure repeats the question.
    session.advance_setup(asked_at)
    return Response(content=wav, media_type="audio/wav")


def _proposal_yes(record: dict, proposal: dict, asked_at: datetime) -> Response:
    """A yes writes the proposed value, or for a confirmation re-stamps the date and keeps
    the value; the answer says what happened. The proposal is consumed once spoken, so a
    failed answer can be retried (FR-31, FR-30)."""
    slot, value = proposal["slot"], proposal["value"]
    spoken_slot = slot.replace("_", " ")
    try:
        profile.write(slot, value, asked_at.date())
    except profile.ProfileError as e:
        record["answer"] = f"I could not save that: {_reason(e)}"
    else:
        if proposal["kind"] == "confirm":
            record["answer"] = f"Okay, I kept your {spoken_slot}: {value}."
        else:
            record["answer"] = f"Saved. Your {spoken_slot} is now: {value}."
    wav = run_stage("tts", record["timings_ms"], tts.synthesize, record["answer"])
    session.end_proposal()
    return Response(content=wav, media_type="audio/wav")


def _proposal_no(record: dict, proposal: dict) -> Response:
    """A no writes nothing; a declined update is not proposed again this session, a
    declined confirmation is not a decline of the slot (FR-31)."""
    record["answer"] = "Okay, nothing changed."
    wav = run_stage("tts", record["timings_ms"], tts.synthesize, record["answer"])
    if proposal["kind"] == "update":
        session.decline(proposal["slot"])
    session.end_proposal()
    return Response(content=wav, media_type="audio/wav")


def _stale_line(asked_at: datetime) -> str | None:
    """The line asking whether the month goal still holds, or None: said once per session,
    and not when the model has just asked something else (FR-30)."""
    days = profile.stale_days(asked_at.date())
    if (
        days is None
        or session.stale_noted(asked_at)
        or session.proposal(asked_at) is not None
    ):
        return None
    return config.GOAL_STALE_LINE.format(days=days)


def _answer(data: bytes | None, image: bytes | None, record: dict) -> Response:
    if problem := _audio_problem(data):
        return _error(400, problem, record)
    new_image = None
    if image is not None:
        if len(image) > config.IMAGE_MAX_BYTES:
            return _error(400, "image too large", record)
        if not (mime_type := _image_type(image)):
            return _error(400, "image is not a readable image", record)
        new_image = (image, mime_type)
        record["image_sent"] = True
    timings = record["timings_ms"]
    try:
        record["question"] = run_stage("stt", timings, stt.transcribe, data)
        if not record["question"].strip():
            return _error(400, "no speech detected", record)
        asked_at = now()
        if quiz := session.quiz(asked_at):
            return _quiz_answer(record, quiz, asked_at)
        if setup := session.setup(asked_at):
            return _setup_answer(record, setup, asked_at)
        if session.pending_wipe(asked_at):
            return _wipe_confirm(record)
        if proposal := session.proposal(asked_at):
            spoken_phrase = _normalised(record["question"])
            if spoken_phrase in config.PROPOSAL_YES:
                return _proposal_yes(record, proposal, asked_at)
            if spoken_phrase in config.PROPOSAL_NO:
                return _proposal_no(record, proposal)
            # Neither: drop it and answer as a normal query, the safe failure.
            session.end_proposal()
        if (slots := _setup_slots()) and not session.setup_stopped():
            return _setup_start(record, slots, asked_at)
        spoken = f" {_normalised(record['question'])} "
        if f" {config.WIPE_REQUEST_PHRASE} " in spoken:
            return _wipe_request(record, asked_at)
        turns = session.turns(asked_at)
        record["session_continued"] = bool(turns)
        # A text follow-up is about the screenshot saved with an earlier turn (FR-21).
        image_for_llm = new_image or session.image(asked_at)
        record["answer"], record["searched"], record["tool_calls"] = run_stage(
            "llm", timings, llm.ask, record["question"], asked_at, turns, image_for_llm
        )
        stale_line = _stale_line(asked_at)
        if stale_line:
            record["answer"] = f"{record['answer']} {stale_line}"
        wav = run_stage("tts", timings, tts.synthesize, record["answer"])
        # Only an answered question becomes a turn, so a failure never extends the session (FR-21).
        session.add_turn(
            record["question"],
            record["answer"],
            asked_at,
            image=new_image,
            stale_noted=bool(stale_line),
        )
        if stale_line:
            # A yes to the line re-stamps the goal's date; the value stays as it is (FR-30).
            slot = config.GOAL_STALE_SLOT
            session.propose("confirm", slot, profile.values()[slot], asked_at)
    except StageFailed as e:
        record["tool_calls"] = e.tool_calls or record["tool_calls"]
        return _error(500, f"{e.stage}: {e.reason}", record)
    return Response(content=wav, media_type="audio/wav")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


@app.post("/session/reset")
def session_reset() -> dict:
    session.reset()
    return {"status": "ok"}


def _write_session(at: datetime) -> None:
    """Write at most one expired session's points to memory and leave a spoken notice for the
    poll to deliver (FR-39). Nothing here may fail the poll, which also delivers reminders."""
    turns = session.take_expired(at)
    if turns is None:
        return
    # Counts and the guard's drops only. An ungrounded drop carries its text, which is the model's
    # own invention; no stored memory and none of the user's turns ever reach the log (FR-17).
    record = {
        "event": "session_writer",
        "turns": len(turns),
        "points_returned": 0,
        "rows_added": 0,
        "points_too_long": 0,
        "points_rejected": 0,
        "dropped": [],
        "timings_ms": {},
        "error": None,
    }
    try:
        points = run_stage("llm", record["timings_ms"], llm.write_memories, turns, at)
        record["points_returned"] = len(points)
        # The user's words only: the guard grounds a point in what the user said (FR-40).
        user_text = " ".join(turn["question"] for turn in turns)
        profile_text = " ".join(profile.values().values())
        stored = tools.store_points(points, user_text, profile_text, at)
        record["rows_added"] = stored["added"]
        record["points_too_long"] = stored["too_long"]
        record["dropped"] = stored["dropped"]
        record["points_rejected"] = stored["too_long"] + len(stored["dropped"])
        if stored["added"]:
            store.add_notice(
                tools.writer_notice(stored["added"]), at.isoformat(timespec="seconds")
            )
    except Exception as e:  # noqa: BLE001  a failed writer loses its points, nothing more
        record["error"] = _reason(e)
    finally:
        logger.log_query(record)


@app.get("/reminders/due")
def reminders_due() -> Response:
    _write_session(now())
    # Read the clock again: the writer may have taken seconds and its notice is due at its start.
    due = store.list_due(now().isoformat(timespec="seconds"))
    if not due:
        return Response(status_code=204)
    return JSONResponse(content=due)


def _find_reminder(reminder_id: str, lookup) -> dict | None:
    """Apply lookup to the id; None when it isn't a usable id, so the caller answers 404."""
    # The id is a string so a non-numeric one is a 404, not FastAPI's 422.
    if not (reminder_id.isascii() and reminder_id.isdigit()):
        return None
    try:
        return lookup(int(reminder_id))
    # Too large for int() (over 4300 digits) or for an SQLite integer: no such reminder.
    except (ValueError, OverflowError):
        return None


def _reminder_not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "reminder not found"})


@app.post("/reminders/{reminder_id}/ack")
def reminder_ack(reminder_id: str) -> Response:
    if _find_reminder(reminder_id, store.ack) is None:
        return _reminder_not_found()
    return JSONResponse(content={"status": "ok"})


@app.get("/reminders/{reminder_id}/audio")
def reminder_audio(reminder_id: str) -> Response:
    reminder = _find_reminder(reminder_id, store.get)
    if reminder is None:
        return _reminder_not_found()
    wav = tts.synthesize(tools.reminder_text(reminder, now()))
    return Response(content=wav, media_type="audio/wav")


# Plain def, not async: FastAPI runs it in a thread pool, so a slow query doesn't block other endpoints.
@app.post("/query")
def query(
    audio: Annotated[UploadFile | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
) -> Response:
    record = {
        "question": None,
        "answer": None,
        "timings_ms": {},
        "searched": False,
        "tool_calls": [],
        "error": None,
        "session_continued": False,
        "image_sent": False,
    }
    try:
        return _answer(
            audio.file.read() if audio else None,
            image.file.read() if image else None,
            record,
        )
    finally:
        record["concept"] = _concept(record["tool_calls"])
        record["memories_used"] = _memories_used(record["tool_calls"])
        record["profile_lines"] = profile.line_count()
        logger.log_query(record)


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
