# Local test runbook

## 1. Preflight

```bash
podman --version
df -h .
cp .env.local.example .env.local
```

The containers run rootless. Container UID 0 maps to the invoking host user and is used only so all
services can write the shared bind mount without changing ownership on the host.

## 2. Validate the configuration

```bash
podman compose --env-file .env.local -f compose.yml -f compose.local.yml config
```

## 3. Build and run

```bash
podman compose --env-file .env.local -f compose.yml -f compose.local.yml up -d --build
podman compose --env-file .env.local -f compose.yml -f compose.local.yml ps
curl -fsS http://127.0.0.1:8090/api/health
```

Use fixture first. Inspect its run and create `v1.3.0` from the dashboard. Then run sample. Full sync
should be attempted only after sample has zero asset-download and offline-validation errors.

## 4. Test Electron offline

```bash
npm ci
npm start
```

Open pages, switch all languages, search, navigate back/home and inspect representative images. Then
disconnect the network and repeat. External links should request the system browser; page rendering
must not perform network requests.

## 5. Build Linux packages

Open **Candidates**, choose an edition and **Linux — ZIP + DEB + RPM**, then press **Generate
builds**. Open **Builds** and use the manual **Refresh** button to inspect queued/building/completed
state, progress and logs. The persistent `builder-worker` performs the work without access to the
Podman socket.

The equivalent one-shot command uses the newest candidate by default, not `current.json`:

```bash
podman compose --profile tools --env-file .env.local -f compose.yml -f compose.local.yml run --rm linux-builder
find .local-data/builds -type f -maxdepth 8 -print
```

Install/test the DEB or RPM only on a suitable disposable/test environment. The ZIP can be extracted
without changing the system.

## 6. Preserve data when stopping

```bash
podman compose --env-file .env.local -f compose.yml -f compose.local.yml down
```

Never use `down -v` as a routine stop command. It deletes named builder volumes. Removing
`.local-data` also deletes local snapshots, candidates and audit history.
