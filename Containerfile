FROM docker.io/library/python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tar zstd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY wiki_updater ./wiki_updater
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 updater \
    && mkdir -p /data \
    && chown updater:updater /data
USER updater

EXPOSE 8080
COPY production-seed /opt/wiki-seed

CMD ["wiki-updater", "production"]
