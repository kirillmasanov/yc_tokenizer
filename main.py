import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

MAX_TEXT_LENGTH = 1_000_000  # ~1 МБ — защита от слишком больших запросов

load_dotenv()

YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID", "")

TOKENIZE_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/tokenize"

# Модели, для которых токенизация выполняется локально (Hugging Face), т.к. Yandex API не отдаёт токенизатор
LOCAL_TOKENIZER_MODELS = {"qwen3-235b-a22b-fp8", "qwen3.6-35b-a3b", "gpt-oss-120b", "gpt-oss-20b", "deepseek-v32"}

# Модели, которые не поддерживают токенизацию через API — используем токенизатор-прокси
TOKENIZER_PROXY: dict[str, str] = {
    "aliceai-llm": "yandexgpt/latest",  # Alice AI основана на YandexGPT
}
LOCAL_TOKENIZER_HF_MODEL: dict[str, str] = {
    "qwen3-235b-a22b-fp8": "Qwen/Qwen3-0.6B",
    "qwen3.6-35b-a3b": "Qwen/Qwen3-0.6B",
    "gpt-oss-120b": "openai/gpt-oss-120b",
    "gpt-oss-20b": "openai/gpt-oss-20b",
    "deepseek-v32": "deepseek-ai/DeepSeek-V3",
}

AVAILABLE_MODELS = [
    {"id": "yandexgpt/latest", "name": "YandexGPT Pro 5", "context": "32768", "price_per_1000": 1.20},
    {"id": "yandexgpt/rc", "name": "YandexGPT Pro 5.1", "context": "32768", "price_per_1000": 0.80},
    {"id": "yandexgpt-lite", "name": "YandexGPT Lite 5", "context": "32768", "price_per_1000": 0.20},
    {"id": "aliceai-llm", "name": "Alice AI LLM", "context": "32768", "price_per_1000": 0.50},
    {"id": "qwen3-235b-a22b-fp8", "name": "Qwen3 235B A22B (FP8)", "context": "262144", "price_per_1000": 0.50},
    {"id": "qwen3.6-35b-a3b", "name": "Qwen3.6 35B A3B", "context": "262144", "price_per_1000": 0.20},
    {"id": "gpt-oss-120b", "name": "GPT-OSS 120B", "context": "131072", "price_per_1000": 0.30},
    {"id": "gpt-oss-20b", "name": "GPT-OSS 20B", "context": "131072", "price_per_1000": 0.10},
    {"id": "deepseek-v32", "name": "DeepSeek V3.2", "context": "131072", "price_per_1000": 0.50},
]

# Кэш токенизаторов Hugging Face (model_id -> tokenizer)
_hf_tokenizer_cache: dict[str, Any] = {}
_hf_tokenizer_locks: dict[str, asyncio.Lock] = {}


async def _get_local_tokenizer(model_id: str):
    """Ленивая загрузка и кэширование токенизатора. Блокировка предотвращает
    повторную загрузку при одновременных запросах для одной модели."""
    if model_id in _hf_tokenizer_cache:
        return _hf_tokenizer_cache[model_id]
    hf_model_id = LOCAL_TOKENIZER_HF_MODEL.get(model_id)
    if not hf_model_id:
        raise ValueError(f"Unknown local tokenizer model: {model_id}")

    lock = _hf_tokenizer_locks.setdefault(model_id, asyncio.Lock())
    async with lock:
        if model_id in _hf_tokenizer_cache:
            return _hf_tokenizer_cache[model_id]
        try:
            from transformers import AutoTokenizer

            tokenizer = await asyncio.to_thread(AutoTokenizer.from_pretrained, hf_model_id)
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Не удалось загрузить токенизатор ({hf_model_id}): {e}",
            ) from e
        _hf_tokenizer_cache[model_id] = tokenizer
        return tokenizer


async def _tokenize_local(model_id: str, text: str) -> tuple[list["TokenInfo"], str]:
    """Токенизация текста локальным (Hugging Face) токенизатором. Возвращает (tokens, model_version)."""
    tokenizer = await _get_local_tokenizer(model_id)
    try:
        ids = tokenizer.encode(text, add_special_tokens=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка токенизации: {e}") from e
    special_ids = set(tokenizer.all_special_ids)
    # decode([id]) даёт корректный Unicode для одного токена (convert_ids_to_tokens даёт mojibake для кириллицы)
    tokens = [
        TokenInfo(
            id=tid,
            text=tokenizer.decode([tid]),
            special=tid in special_ids,
        )
        for tid in ids
    ]
    if "gpt-oss" in model_id:
        model_version = "local (GPT-OSS)"
    elif "deepseek" in model_id:
        model_version = "local (DeepSeek)"
    else:
        model_version = "local (Qwen3)"
    return tokens, model_version


app = FastAPI(title="YC Tokenizer")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class TokenizeRequest(BaseModel):
    model: str
    text: str = Field(max_length=MAX_TEXT_LENGTH)


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
        "default": AVAILABLE_MODELS[0]["id"] if AVAILABLE_MODELS else None,
    }


@app.get("/api/health")
async def health():
    """Health check для Docker и мониторинга."""
    return {"status": "ok"}


_KNOWN_MODEL_IDS = {m["id"] for m in AVAILABLE_MODELS}


@app.post("/api/tokenize", response_model=TokenizeResponse)
async def tokenize(req: TokenizeRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty")

    if req.model not in _KNOWN_MODEL_IDS:
        raise HTTPException(status_code=400, detail=f"Unknown model: {req.model}")

    if req.model in LOCAL_TOKENIZER_MODELS:
        tokens, model_version = await _tokenize_local(req.model, req.text)
        return TokenizeResponse(
            token_count=len(tokens),
            tokens=tokens,
            model_version=model_version,
        )

    if not YANDEX_API_KEY or not YANDEX_FOLDER_ID:
        raise HTTPException(
            status_code=503,
            detail="YANDEX_API_KEY и YANDEX_FOLDER_ID не настроены в .env",
        )

    api_model = TOKENIZER_PROXY.get(req.model, req.model)
    model_uri = f"gpt://{YANDEX_FOLDER_ID}/{api_model}"

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
            raise HTTPException(status_code=502, detail=f"Yandex API request failed: {e}") from e

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
