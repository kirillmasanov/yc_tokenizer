# YC Tokenizer — подсчёт токенов для моделей Yandex Cloud AI Studio

Веб-приложение для токенизации текста и оценки стоимости запросов к моделям Yandex Cloud AI Studio (YandexGPT, Qwen3, GPT-OSS и др.). Поддерживаются модели с токенизацией через API Yandex и модели с локальной токенизацией (Hugging Face).

## Что это?

- **Выбор модели** — YandexGPT Pro 5, YandexGPT Lite, Alice AI, Qwen3 235B, GPT-OSS 120B/20B и др.
- **Токенизация** — ввод текста или загрузка файла, подсчёт токенов, подсветка в тексте.
- **Оценка стоимости** — расчёт в рублях за 1000 или за 1 млн токенов (вкл. НДС).
- **Локальные модели** — для Qwen3 и GPT-OSS токенизатор подгружается с Hugging Face (Yandex API токенизатор для них не отдаёт).

Актуальные цены: [yandex.cloud/ru/docs/ai-studio/pricing](https://yandex.cloud/ru/docs/ai-studio/pricing)

## Структура проекта

```
yc_tokenizer/
├── .env.example      # Пример конфигурации
├── pyproject.toml    # Зависимости (uv)
├── uv.lock           # Lock-файл зависимостей
├── Dockerfile        # Сборка Docker-образа
├── main.py           # FastAPI: API и логика токенизации
├── static/
│   └── index.html    # Веб-интерфейс
└── README.md
```

## Быстрый старт

### 1. Установка зависимостей

```bash
# Установить зависимости и создать виртуальное окружение
uv sync

# Активировать окружение (опционально)
source .venv/bin/activate   # macOS/Linux
```

**Примечание:** если не установлен uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`

### 2. Настройка

Для моделей Yandex (YandexGPT, Alice AI и т.д.) нужны ключ и каталог. Создайте `.env` в корне:

```bash
cp .env.example .env
# Отредактировать .env: YANDEX_API_KEY, YANDEX_FOLDER_ID
```

Содержимое `.env`:

```
YANDEX_API_KEY=your_api_key_here
YANDEX_FOLDER_ID=your_folder_id_here
```

Модели с локальной токенизацией (Qwen3, GPT-OSS) работают без ключа Yandex; при первом запросе скачивается токенизатор с Hugging Face.

### 3. Запуск

#### Вариант 1: Локальный запуск

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Приложение: **http://localhost:8000**

#### Вариант 2: Docker

```bash
# Сборка образа
docker build -t yc-tokenizer .

# Запуск (передать .env или переменные окружения)
docker run -p 8000:8000 --env-file .env yc-tokenizer
```

Приложение: **http://localhost:8000**

## Использование

1. Откройте http://localhost:8000 в браузере.
2. Выберите модель (YandexGPT, Qwen3, GPT-OSS и др.).
3. Введите текст в поле или нажмите **Select Files** и загрузите текстовый файл.
4. Нажмите **Calculate Tokens**.
5. В блоке результатов: число токенов, оценка стоимости (вкл. НДС), подсветка токенов в тексте, список токенов.
6. При необходимости включите галочку **Тарификация за 1 млн токенов** — цены и стоимость отобразятся в расчёте на 1 млн токенов.

## API

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/` | Веб-интерфейс |
| GET | `/api/health` | Health check (Docker, мониторинг) |
| GET | `/api/models` | Список моделей и тарифов |
| POST | `/api/tokenize` | Токенизация текста |

### Токенизация

```bash
curl -X POST http://localhost:8000/api/tokenize \
  -H "Content-Type: application/json" \
  -d '{"model": "yandexgpt/latest", "text": "Привет, мир!"}'
```

Ответ: `token_count`, `tokens` (массив `{id, text, special}`), `model_version`.

## Как это работает

- **Модели Yandex** (YandexGPT, Alice AI и т.д.): запрос к `foundationModels/v1/tokenize` в Yandex Cloud. Требуются `YANDEX_API_KEY` и `YANDEX_FOLDER_ID`.
- **Локальные модели** (Qwen3 235B, GPT-OSS 120B, GPT-OSS 20B): Yandex не отдаёт для них токенизатор по API. Приложение использует токенизаторы с Hugging Face (`transformers`). При первом запросе по каждой такой модели токенизатор скачивается и кэшируется в памяти.

Тарифы в интерфейсе заданы в коде; актуальные цены см. в [документации Yandex Cloud](https://yandex.cloud/ru/docs/ai-studio/pricing).
