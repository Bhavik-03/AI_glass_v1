import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, File, Response, UploadFile

from server import config, llm, stt, tts


@asynccontextmanager
async def lifespan(app: FastAPI):
    stt.load()
    tts.load()
    yield


app = FastAPI(lifespan=lifespan)


def now() -> datetime:
    return datetime.now(ZoneInfo(config.TIMEZONE))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


# Plain def, not async: FastAPI runs it in a thread pool, so a slow query doesn't block other endpoints.
@app.post("/query")
def query(audio: Annotated[UploadFile | None, File()] = None) -> Response:
    question = stt.transcribe(audio.file.read())
    answer, _searched, _tool_calls = llm.ask(question, now())
    return Response(content=tts.synthesize(answer), media_type="audio/wav")


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
