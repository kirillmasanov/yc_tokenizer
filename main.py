import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")
YANDEX_CLOUD_MODEL = os.getenv("YANDEX_CLOUD_MODEL", "yandexgpt/latest")

TOKENIZE_URL = "https://ai.api.cloud.yandex.net/foundationModels/v1/tokenize"

AVAILABLE_MODELS = [
    {"id": "yandexgpt/latest", "name": "YandexGPT Pro 5", "context": "32K"},
    {"id": "yandexgpt/rc", "name": "YandexGPT Pro 5.1", "context": "32K"},
    {"id": "yandexgpt-lite", "name": "YandexGPT Lite 5", "context": "32K"},
    {"id": "aliceai-llm", "name": "Alice AI LLM", "context": "32K"},
]

app = FastAPI(title="YC Tokenizer")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class TokenizeRequest(BaseModel):
    model: str
    text: str


class TokenInfo(BaseModel):
    id: int
    text: str
    special: bool


class TokenizeResponse(BaseModel):
    token_count: int
    tokens: list[TokenInfo]
    model_version: str


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/models")
async def get_models():
    return {
        "models": AVAILABLE_MODELS,
        "default": YANDEX_CLOUD_MODEL,
    }


@app.post("/api/tokenize", response_model=TokenizeResponse)
async def tokenize(req: TokenizeRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty")

    model_uri = f"gpt://{YANDEX_FOLDER_ID}/{req.model}"

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                TOKENIZE_URL,
                headers={
                    "Authorization": f"Api-Key {YANDEX_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "modelUri": model_uri,
                    "text": req.text,
                },
            )
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Yandex API request failed: {e}")

    if resp.status_code != 200:
        detail = f"Yandex API error: {resp.text}"
        if resp.status_code == 500 and "code" in resp.text and "13" in resp.text:
            detail += " Попробуйте модель YandexGPT (Pro 5 или Lite 5) — не все модели поддерживают токенизацию."
        raise HTTPException(status_code=resp.status_code, detail=detail)

    data = resp.json()
    tokens = [
        TokenInfo(id=t["id"], text=t["text"], special=t["special"])
        for t in data.get("tokens", [])
    ]

    return TokenizeResponse(
        token_count=len(tokens),
        tokens=tokens,
        model_version=data.get("modelVersion", ""),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
