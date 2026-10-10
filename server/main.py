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

from server import config, llm, stt, tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    stt.load()
    tts.load()
    yield


app = FastAPI(lifespan=lifespan)


class StageFailed(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


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
        raise StageFailed(name, _reason(e)) from e
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


def _error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


# Plain def, not async: FastAPI runs it in a thread pool, so a slow query doesn't block other endpoints.
@app.post("/query")
def query(audio: Annotated[UploadFile | None, File()] = None) -> Response:
    data = audio.file.read() if audio else None
    if problem := _audio_problem(data):
        return _error(400, problem)
    timings: dict[str, int] = {}
    try:
        question = run_stage("stt", timings, stt.transcribe, data)
        if not question.strip():
            return _error(400, "no speech detected")
        answer, _searched, _tool_calls = run_stage(
            "llm", timings, llm.ask, question, now()
        )
        wav = run_stage("tts", timings, tts.synthesize, answer)
    except StageFailed as e:
        return _error(500, f"{e.stage}: {e.reason}")
    return Response(content=wav, media_type="audio/wav")


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
