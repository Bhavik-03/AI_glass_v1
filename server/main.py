import uvicorn
from fastapi import FastAPI

from server import config

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": config.LLM_MODEL}


if __name__ == "__main__":
    uvicorn.run(app, host=config.HOST, port=config.PORT)
