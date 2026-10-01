FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HEADLESS=true \
    POLL_INTERVAL_MINUTES=30 \
    FACEBOOK_STORAGE_STATE=/data/storage_state.json

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py config.yaml ./
COPY src ./src

RUN mkdir -p /data /app/data

VOLUME ["/data", "/app/data"]

# Always-on watcher (sleeps POLL_INTERVAL_MINUTES between scans)
CMD ["python", "main.py"]
