import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from server import config, stt


@asynccontextmanager
async def lifespan(app: FastAPI):
    stt.load()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


if __name__ == "__main__":
    logging.basicConfig(level=config.LOG_LEVEL)
    uvicorn.run(app, host=config.HOST, port=config.PORT)
