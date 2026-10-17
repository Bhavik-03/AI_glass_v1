import io
import logging
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

from server import config, llm, logger, session, store, stt, tools, tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
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


def _error(status_code: int, message: str, record: dict) -> JSONResponse:
    record["error"] = message
    return JSONResponse(status_code=status_code, content={"error": message})


def _quiz_answer(record: dict, quiz: dict, asked_at: datetime) -> Response:
    """Grade the transcript as the answer to the current quiz question and speak the
    feedback plus the next question or the score (FR-24)."""
    timings = record["timings_ms"]
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
        turns = session.turns(asked_at)
        record["session_continued"] = bool(turns)
        # A text follow-up is about the screenshot saved with an earlier turn (FR-21).
        image_for_llm = new_image or session.image(asked_at)
        record["answer"], record["searched"], record["tool_calls"] = run_stage(
            "llm", timings, llm.ask, record["question"], asked_at, turns, image_for_llm
        )
        wav = run_stage("tts", timings, tts.synthesize, record["answer"])
        # Only an answered question becomes a turn, so a failure never extends the session (FR-21).
        session.add_turn(
            record["question"], record["answer"], asked_at, image=new_image
        )
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


@app.get("/reminders/due")
def reminders_due() -> Response:
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
        logger.log_query(record)


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
