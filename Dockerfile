# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --target=/install -r requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash velox

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.11/site-packages

RUN playwright install-deps chromium && playwright install chromium \
    && rm -rf /tmp/* /var/lib/apt/lists/*

COPY . .

RUN chown -R velox:velox /app

USER velox

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import asyncio; asyncio.run(__import__('motor.motor_asyncio').AsyncIOMotorClient('mongodb://mongo:27017').admin.command('ping'))"

CMD ["python", "-m", "bot.main"]
