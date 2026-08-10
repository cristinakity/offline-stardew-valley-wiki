FROM docker.io/library/node:22-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends fakeroot rpm zip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY scripts/build-linux.sh /usr/local/bin/build-linux
RUN chmod 0755 /usr/local/bin/build-linux
ENTRYPOINT ["build-linux"]
