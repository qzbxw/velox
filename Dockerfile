FROM python:3.11-slim

# Install basic tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and its system dependencies
# This command automatically handles all the libs we were trying to list manually
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
