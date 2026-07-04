FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libasound2 \
        libgtk-3-0 \
        libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m camoufox fetch

COPY config.toml run.py notify.example.sh ./
COPY stockmonitor ./stockmonitor

RUN mkdir -p /app/data

VOLUME ["/app/data"]
ENTRYPOINT ["python", "-m", "stockmonitor"]
