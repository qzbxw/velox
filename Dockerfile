FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg && rm -rf /var/lib/apt/lists/*

# Create a non-root user
RUN useradd -m -s /bin/bash velox

WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright dependencies (as root)
RUN python -m playwright install-deps chromium

# Copy the application code
COPY . .

# Change ownership to the non-root user
RUN chown -R velox:velox /app

USER velox

# Install Playwright browser (as velox user)
ENV PLAYWRIGHT_BROWSERS_PATH=/home/velox/.cache/ms-playwright
RUN python -m playwright install chromium

ENV PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import asyncio, os; asyncio.run(__import__('motor.motor_asyncio').AsyncIOMotorClient(os.getenv('MONGO_URI', 'mongodb://mongo:27017')).admin.command('ping'))"

CMD ["python", "-m", "bot.main"]
