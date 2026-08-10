# Full snapshot and production deployment through the broker

This runbook transfers an approved local `full` snapshot to production and deploys the crawler
without direct server access. Replace every value enclosed in `<...>` before running a command.

## Safety gates

Do not continue until all of these are true:

1. The local `full` run is `completed` and its validation reports zero broken links, missing assets,
   remote resources and asset download errors.
2. The desktop reader has been tested offline in all enabled languages.
3. A local candidate has been created and approved.
4. The broker grant has a persistent named volume mounted at `/data`.

The last requirement is mandatory. The current broker implementation must support a fixed volume
mapping in the grant before this workflow is enabled. A deployment without it would lose SQLite,
history and snapshots whenever the container is replaced. Keep the repository variable
`BROKER_PERSISTENT_DATA_READY` unset until that capability exists and has been tested.

## 1. Create the candidate locally

After the dashboard shows the `full` run as completed, enter a release version under
**Create candidate** and select **Create**. Alternatively:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm cli candidate --version <VERSION>
```

Find the generated archive:

```bash
find ".local-data/candidates/<VERSION>" \
  -maxdepth 1 \
  -name 'wiki-content-*.tar.zst' \
  -type f
```

Verify every candidate asset before uploading anything:

```bash
cd ".local-data/candidates/<VERSION>"
sha256sum --check SHA256SUMS
cd -
```

Do not use an archive from a `fixture` or `sample` candidate as the initial production snapshot.

## 2. Publish the snapshot as an OCI artifact

Install ORAS locally and authenticate to the registry using a token with package write permission:

```bash
export REGISTRY_USER='<REGISTRY_USER>'
export REGISTRY_TOKEN='<REGISTRY_WRITE_TOKEN>'
printf '%s' "$REGISTRY_TOKEN" | oras login ghcr.io -u "$REGISTRY_USER" --password-stdin
```

Choose a package name and immutable release tag:

```bash
export SNAPSHOT_TAG='ghcr.io/<OWNER>/offline-stardew-valley-wiki-snapshot:<VERSION>'
export SNAPSHOT_ARCHIVE="$(find ".local-data/candidates/<VERSION>" \
  -maxdepth 1 -name 'wiki-content-*.tar.zst' -type f -print -quit)"

test -n "$SNAPSHOT_ARCHIVE"
scripts/publish-snapshot.sh "$SNAPSHOT_ARCHIVE" "$SNAPSHOT_TAG"
```

Resolve the tag to a digest and save the complete immutable reference:

```bash
export SNAPSHOT_DIGEST="$(oras resolve "$SNAPSHOT_TAG")"
export SNAPSHOT_REF="${SNAPSHOT_TAG}@${SNAPSHOT_DIGEST}"
printf '%s\n' "$SNAPSHOT_REF"
```

The deployment workflow accepts only a reference containing `@sha256:`. A mutable tag by itself is
rejected.

## 3. Configure the broker grant

Create or update the grant through the broker's private administrative interface:

```text
App ID: offline-stardew-wiki-updater
GitHub repository: <OWNER>/<REPOSITORY>
GitHub ref: refs/heads/<PRODUCTION_BRANCH>
Allowed image prefix: ghcr.io/<OWNER>/offline-stardew-valley-wiki-updater
Route mode: single
Domain: <UPDATER_DOMAIN>
Container name: offline-stardew-wiki-updater
Upstream port: 8080
Health path: /api/health
Persistent volume: offline_stardew_wiki_updater_data:/data
```

Configure these fixed environment values in the grant:

```json
{
  "APP_ENV": "production",
  "BIND_HOST": "0.0.0.0",
  "DATA_DIR": "/data",
  "DATABASE_PATH": "/data/updater.sqlite3",
  "STORAGE_LIMIT_GB": "15",
  "MIN_FREE_GB": "3",
  "SNAPSHOT_RETENTION": "3",
  "TIMEZONE": "America/Chicago",
  "HTTP_CONCURRENCY": "2",
  "PAGE_CONCURRENCY": "2",
  "GITHUB_OAUTH_CLIENT_ID": "<OAUTH_CLIENT_ID>",
  "GITHUB_OAUTH_CLIENT_SECRET": "<OAUTH_CLIENT_SECRET>",
  "GITHUB_ALLOWED_USERS": "<ALLOWED_LOGIN>",
  "SESSION_SECRET": "<RANDOM_SECRET_AT_LEAST_32_CHARACTERS>"
}
```

The OAuth callback is:

```text
https://<UPDATER_DOMAIN>/auth/callback
```

The production container runs the dashboard and scheduler together because the broker deploys one
image as one container. On the first start, if `/data/current.json` does not exist, it imports the
approved seed bundled into the image. On later deploys it preserves and reuses the existing volume.

## 4. Configure the GitHub `production` environment

Create an environment named `production`, require manual reviewers, and add:

Variables:

```text
DEPLOY_BROKER_URL=https://<BROKER_DOMAIN>
DEPLOY_BROKER_AUDIENCE=<BROKER_OIDC_AUDIENCE>
DEPLOY_BROKER_APP_ID=offline-stardew-wiki-updater
BROKER_PERSISTENT_DATA_READY=true
```

Secret:

```text
GHCR_READ_TOKEN=<TOKEN_WITH_PACKAGE_READ_PERMISSION>
```

No host address, operating-system user, private key or server credential belongs in this
repository or GitHub environment.

## 5. Deploy without direct server access

Open GitHub Actions and run **Deploy updater to production** with:

```text
confirmation: DEPLOY-PRODUCTION
snapshot_ref: <SNAPSHOT_REF_FROM_STEP_2>
```

The workflow will:

1. Reject the run unless persistent broker storage was explicitly approved.
2. Download the snapshot by immutable digest.
3. Build a production image containing that compressed seed.
4. Push the image to GHCR using the commit SHA as its tag.
5. Request a GitHub OIDC token for the configured broker audience.
6. Ask the broker to deploy the exact image.
7. Let the container validate and import the seed only when `/data` is empty.

The workflow contains no direct remote shell, file-copy or host-login step.

## 6. Verify production

Open these URLs:

```text
https://<UPDATER_DOMAIN>/api/health
https://<UPDATER_DOMAIN>/
```

The health response must include:

```json
{"status":"ok","environment":"production","version":"0.1.0"}
```

In the dashboard confirm:

- The imported snapshot ID matches the approved local candidate.
- No import run failed.
- Storage remains below 15 GiB.
- The scheduler and enabled languages match the intended configuration.
- An `incremental` run processes only changes instead of downloading the complete wiki.

## 7. Later deployments and updates

The named volume remains authoritative across image replacements. A bundled seed is ignored when
`/data/current.json` already exists. Normal operation is:

```text
weekly: incremental synchronization
monthly: full reconciliation while the previous snapshot remains available until validation succeeds
```

The monthly reconciliation is intentionally slower because it verifies and downloads the complete
namespace again; it does not make the currently promoted snapshot unavailable. For a new approved
content baseline, publish another OCI snapshot and invoke the workflow with its new immutable digest.
Never overwrite an existing OCI tag or manually modify files in `/data`.
