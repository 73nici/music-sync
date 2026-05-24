FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg ist Pflicht für yt-dlp (Opus-Extraktion); tini für sauberes Signal-Handling.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY music_sync ./music_sync
RUN pip install --no-cache-dir .

# Nicht-Root User für Sicherheit. Default-UID/GID 1000, kann per build-arg überschrieben werden.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} app \
    && useradd -m -u ${APP_UID} -g ${APP_GID} -s /bin/bash app \
    && mkdir -p /config /music /cache \
    && chown -R app:app /config /music /cache /app

USER app

ENV MUSIC_SYNC_CONFIG=/config/config.yaml \
    XDG_CACHE_HOME=/cache

VOLUME ["/music", "/config", "/cache"]

ENTRYPOINT ["/usr/bin/tini", "--", "music-sync", "--config", "/config/config.yaml"]
CMD ["--help"]
