import io
import logging
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


def now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


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


def _bad_request(reason: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": reason})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


# Plain def, not async: FastAPI runs it in a thread pool, so a slow query doesn't block other endpoints.
@app.post("/query")
def query(audio: Annotated[UploadFile | None, File()] = None) -> Response:
    data = audio.file.read() if audio else None
    if problem := _audio_problem(data):
        return _bad_request(problem)
    question = stt.transcribe(data)
    if not question.strip():
        return _bad_request("no speech detected")
    answer, _searched, _tool_calls = llm.ask(question, now())
    return Response(content=tts.synthesize(answer), media_type="audio/wav")


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
