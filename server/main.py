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

from server import config, llm, logger, store, stt, tts


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


def _error(status_code: int, message: str, record: dict) -> JSONResponse:
    record["error"] = message
    return JSONResponse(status_code=status_code, content={"error": message})


def _answer(data: bytes | None, record: dict) -> Response:
    if problem := _audio_problem(data):
        return _error(400, problem, record)
    timings = record["timings_ms"]
    try:
        record["question"] = run_stage("stt", timings, stt.transcribe, data)
        if not record["question"].strip():
            return _error(400, "no speech detected", record)
        record["answer"], record["searched"], record["tool_calls"] = run_stage(
            "llm", timings, llm.ask, record["question"], now()
        )
        wav = run_stage("tts", timings, tts.synthesize, record["answer"])
    except StageFailed as e:
        record["tool_calls"] = e.tool_calls or record["tool_calls"]
        return _error(500, f"{e.stage}: {e.reason}", record)
    return Response(content=wav, media_type="audio/wav")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


@app.get("/reminders/due")
def reminders_due() -> Response:
    due = store.list_due(now().isoformat(timespec="seconds"))
    if not due:
        return Response(status_code=204)
    return JSONResponse(content=due)


# Plain def, not async: FastAPI runs it in a thread pool, so a slow query doesn't block other endpoints.
@app.post("/query")
def query(audio: Annotated[UploadFile | None, File()] = None) -> Response:
    record = {
        "question": None,
        "answer": None,
        "timings_ms": {},
        "searched": False,
        "tool_calls": [],
        "error": None,
    }
    try:
        return _answer(audio.file.read() if audio else None, record)
    finally:
        logger.log_query(record)


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
