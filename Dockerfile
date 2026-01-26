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

# Install Playwright system dependencies and chromium
# These layers will be cached as long as requirements.txt is unchanged
RUN playwright install-deps chromium
RUN playwright install chromium

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
