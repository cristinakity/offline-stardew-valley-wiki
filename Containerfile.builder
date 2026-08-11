FROM docker.io/library/node:22-bookworm AS node-runtime

FROM docker.io/library/python:3.13-bookworm

COPY --from=node-runtime /usr/local/ /usr/local/

RUN apt-get update \
    && apt-get install -y --no-install-recommends fakeroot rpm zip zstd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY package.json package-lock.json ./
RUN npm ci
COPY pyproject.toml ./
COPY wiki_updater ./wiki_updater
RUN python3 -m pip install --no-cache-dir .
COPY desktop ./desktop
COPY scripts ./scripts
COPY forge.config.js ./
COPY src/favicon.ico src/favicon.png ./src/
COPY src/flags ./src/flags
COPY src/stardewvalleywiki.com/mediawiki/extensions/StardewValley/images/stardewbackground.png ./src/stardewvalleywiki.com/mediawiki/extensions/StardewValley/images/stardewbackground.png
CMD ["wiki-updater", "build-worker"]
