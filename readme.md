# Offline Stardew Valley Wiki

Desktop reader and local-first synchronization service for a multilingual offline copy of the
[Stardew Valley Wiki](https://www.stardewvalleywiki.com/Stardew_Valley_Wiki).

The current `master` history and historical releases remain untouched. The new updater is designed
to move future wiki snapshots out of Git while keeping code, configuration, tests and small content
manifests in this repository.

## Safety model

The rollout has three independent approval gates:

1. Run and test everything locally with rootless Podman.
2. Build a GitHub draft release and download all five desktop packages.
3. Manually approve the protected `production` environment before any production deployment.

Nothing in the local workflow pushes a branch, publishes a release or contacts production.

## Local requirements

- Podman 5 or newer with `podman compose`/`podman-compose`.
- At least 30 GiB of free disk space for a full crawl.
- Node.js 22 only when running Electron directly on the host.

## Start the local stack

```bash
cp .env.local.example .env.local
podman compose --env-file .env.local -f compose.yml -f compose.local.yml up -d --build
```

Open <http://127.0.0.1:8090>. `LOCAL_PORT` is configurable; local mode refuses non-loopback binding.

Run the deterministic offline fixture:

```bash
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml \
  run --rm cli sync --profile fixture
```

Other profiles:

```bash
# About 25 pages per enabled language
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml \
  run --rm cli sync --profile sample

# Reconcile revisions and update only changed pages from the current snapshot
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml \
  run --rm cli sync --profile incremental

# Complete reconciliation of all enabled languages
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml \
  run --rm cli sync --profile full
```

Create a reviewable local candidate:

```bash
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml \
  run --rm cli candidate --version v1.3.0
```

Build Linux ZIP, DEB and RPM packages:

```bash
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml \
  run --rm linux-builder
```

Stop without deleting data:

```bash
podman compose --env-file .env.local -f compose.yml -f compose.local.yml down
```

Do not add `-v` unless you intentionally want to delete local container volumes.

## Run Electron on the host

After creating a snapshot:

```bash
npm ci
npm start
```

The development app reads `.local-data/current.json`. Packaged builds receive an immutable content
directory through `WIKI_CONTENT_PATH`.

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
npm ci
npm test
```

See [local testing](docs/local-testing.md), [architecture](docs/architecture.md) and the
[production runbook](docs/production-deployment.md) for the complete broker-based workflow. The
[repository migration](docs/repository-migration.md) explains how the historical releases, tags and
issues remain in the same repository when the old mirror is removed in a later normal commit.

## Scheduling

The worker uses `America/Chicago`:

- Sundays at 03:00: incremental synchronization.
- Day 1 of each month at 03:00: complete reconciliation.

The dashboard can pause scheduling or disable individual languages. Only one run may be queued or
active at a time.

## Licensing

Project code is MIT licensed; see [LICENSE](LICENSE). Mirrored wiki content is separately licensed
under CC BY-NC-SA 3.0; see [CONTENT-LICENSE.md](CONTENT-LICENSE.md). The application and snapshots
must remain noncommercial and retain attribution.
