# Offline Stardew Valley Wiki

Multilingual offline desktop reader and local-first updater for the
[Stardew Valley Wiki](https://www.stardewvalleywiki.com/Stardew_Valley_Wiki).

The project has two separate parts:

- **Desktop reader:** Electron application used to browse and search the approved snapshot without
  an Internet connection.
- **Wiki updater:** Podman services that synchronize MediaWiki, validate the result and create
  release candidates.

## Does a Git clone contain the wiki?

The new generated wiki snapshots are deliberately **not stored in Git**. A full snapshot contains
tens of thousands of HTML pages and assets, and committing each version would make every future
clone unnecessarily large.

| Download | Wiki content included? | Intended audience |
| --- | --- | --- |
| ZIP, DEB, RPM or Windows release | Yes | People who only want the offline application |
| Git clone | No new snapshot | Developers and maintainers |
| Approved `wiki-content-*.tar.zst` | Yes | Initializing a development or production environment |

Some legacy HTTrack files may still exist in the repository history while the migration is being
completed. The new reader does not use that mirror. Future generated content lives under
`.local-data/`, which is ignored by Git.

An end user should download an application release. A developer who clones the source can import
the approved `.tar.zst` snapshot and does **not** need to run a four-hour full crawl.

Once `content-lock.json` contains the published OCI digest, a developer can download, verify, and
import that exact approved snapshot with:

```bash
npm run content:pull
```

## Requirements

For the updater and snapshot import:

- Podman 5 or newer.
- `podman compose` or `podman-compose`.
- Python 3.13, `jq` and ORAS when importing the approved OCI snapshot from the host.
- At least 30 GiB free when performing a complete crawl.

For running Electron from the source tree:

- Node.js 22.
- A Linux or Windows graphical desktop.

## Quick start using the approved snapshot

This is the recommended source-development workflow. It installs the exact full snapshot that was
reviewed for a release without crawling the public wiki again.

### 1. Clone and configure

```bash
git clone https://github.com/cristinakity/offline-stardew-valley-wiki.git
cd offline-stardew-valley-wiki
cp .env.local.example .env.local
```

### 2. Start the local updater

```bash
podman compose \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  up -d --build
```

Open the dashboard at <http://127.0.0.1:8090>.

The dashboard is the updater, not the wiki reader. It provides tabs for crawler activity, runs,
candidates, storage, audit history and help.

### 3. Download, verify and import the approved snapshot

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
npm ci
npm run content:pull
```

The command reads the immutable public GHCR reference from `content-lock.json`, downloads it with
ORAS, verifies the archive SHA-256, validates the offline pages and writes `.local-data/current.json`.
Importing does not crawl the Stardew Valley Wiki.

### 4. Open the desktop reader

```bash
env -u ELECTRON_RUN_AS_NODE npm start
```

The development reader loads the snapshot selected by `.local-data/current.json`. Disconnect the
network after it opens to verify that pages, images, translations and search work offline.

## Running the crawler locally

Running the crawler is optional. Use it when testing the synchronization code or producing a newer
snapshot than the currently approved release.

You can start a run from the dashboard or from the CLI.

### Profiles

| Profile | Network | Purpose |
| --- | --- | --- |
| `fixture` | No | Two controlled artificial pages per language; tests Podman, jobs and validation |
| `sample` | Yes | Main page and approximately 24 representative pages per language |
| `incremental` | Yes | Reuses the current snapshot and processes new, changed, moved or deleted pages |
| `full` | Yes | Enumerates and reconciles every available page in all enabled languages |

Run a controlled fixture:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm cli sync --profile fixture
```

Run a real sample:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm cli sync --profile sample
```

Run a complete synchronization:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm cli sync --profile full
```

After a successful full snapshot, routine updates should normally use:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm cli sync --profile incremental
```

## What the crawler does

For every enabled language, the updater:

1. Enumerates pages and revisions through the MediaWiki API.
2. Downloads only the pages required by the selected profile.
3. Downloads and deduplicates images, stylesheets and other local assets.
4. Rewrites internal links, cross-language links, `src`, `srcset`, lazy images and CSS URLs.
5. Removes interactive or online-only elements that cannot work offline.
6. Generates a MiniSearch document collection for each language.
7. Generates `translations.json`, a compact map for fast page and language navigation.
8. Validates page counts, broken links, missing assets and remote resource dependencies.
9. Promotes the snapshot only after structural validation succeeds.

The crawler never sends more than two simultaneous HTTP requests to the wiki. `Parallel pages`
controls local page preparation, not the external request limit. Retries respect `Retry-After` and
use exponential backoff.

If all pages completed but optional assets failed, the dashboard may offer **Recover**. Recovery
rebuilds and validates a snapshot from retained local blobs instead of repeating the entire crawl.

## Languages

The following languages are supported and can be enabled individually:

```text
en es de fr it ja ko hu pt ru tr zh
```

The desktop reader remembers the last language and page. Changing language uses the compact
translation map to open the equivalent article. Full search data is loaded lazily the first time a
search is performed in a language and then remains cached for the current application session.

## Full and lightweight language editions

Application packages can be produced from one approved full snapshot as a multilingual edition or
as one lightweight edition for each of the 12 supported languages:

| Edition | Included content | Package identity |
| --- | --- | --- |
| `multilingual` (alias `full`) | All 12 languages | `Offline Stardew Valley Wiki` |
| `en` | English pages, search and referenced assets only | `Offline Stardew Valley Wiki (EN)` |
| `es` | Spanish pages, search and referenced assets only | `Offline Stardew Valley Wiki (ES)` |
| `de` | German pages, search and referenced assets only | `Offline Stardew Valley Wiki (DE)` |
| `fr` | French pages, search and referenced assets only | `Offline Stardew Valley Wiki (FR)` |
| `it` | Italian pages, search and referenced assets only | `Offline Stardew Valley Wiki (IT)` |
| `ja` | Japanese pages, search and referenced assets only | `Offline Stardew Valley Wiki (JA)` |
| `ko` | Korean pages, search and referenced assets only | `Offline Stardew Valley Wiki (KO)` |
| `hu` | Hungarian pages, search and referenced assets only | `Offline Stardew Valley Wiki (HU)` |
| `pt` | Portuguese pages, search and referenced assets only | `Offline Stardew Valley Wiki (PT)` |
| `ru` | Russian pages, search and referenced assets only | `Offline Stardew Valley Wiki (RU)` |
| `tr` | Turkish pages, search and referenced assets only | `Offline Stardew Valley Wiki (TR)` |
| `zh` | Chinese pages, search and referenced assets only | `Offline Stardew Valley Wiki (ZH)` |

Every language package is an independent lightweight application and can be installed alongside
the others. Language buttons for content not included in that package are hidden. All editions are
derived from the already approved full snapshot, so creating them does not crawl the wiki again.
The official release workflow builds all 12 individual editions on Linux and Windows.

## Local data and storage

All mutable data is visible under `.local-data/`:

```text
.local-data/
├── updater.sqlite3     # runs, settings and audit history
├── blobs/              # content-addressed page and asset storage
├── snapshots/          # promoted logical snapshots
├── candidates/         # archives, reports, checksums and packages
├── builds/              # generated Linux packages
├── backups/            # SQLite backups
├── logs/
└── work/               # temporary synchronization workspaces
```

Snapshots and blobs use hard links, so category sizes may overlap. The dashboard's **Storage real**
value counts physical allocation without counting the same inode multiple times.

The local defaults are a 40 GiB application limit and a 30 GiB minimum free-space reserve. The
dashboard provides explicit, confirmed actions for removing temporary cache, build outputs, old
snapshots and individual candidates.

## Creating a release candidate

After testing the current snapshot in Electron:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm cli candidate --version v2.0.0
```

The candidate directory contains:

- `wiki-content-<snapshot-id>.tar.zst`
- `content-lock.json`
- `validation-report.json`
- `SHA256SUMS`

Creating or publishing a candidate locally does not push to GitHub and does not deploy anything.

## Building Linux packages

The recommended flow is available in the dashboard: open **Candidates**, choose `all`,
`multilingual` or one language, keep **Linux — ZIP + DEB + RPM**, and press **Generate builds**.
The request is persisted in SQLite and consumed sequentially by the separate `builder-worker`.
Use manual **Refresh** in **Builds** to see `queued`, `building`, `completed` or `failed`, edition
progress, logs and downloadable artifacts. **Rebuild** creates a new job using exactly the original
candidate archive and never overwrites the earlier output.

The dashboard and builder worker do not use or mount the Podman socket. Every build extracts the
candidate's immutable `wiki-content-*.tar.zst`; it never builds from `current.json`.
When first queued, that archive is pinned under `.local-data/build-sources/` using a hardlink when
the filesystem supports it. This preserves exact rebuilds without duplicating the physical bytes.

The one-shot CLI remains available. It uses the newest candidate by default. Build its
multilingual/full application:

```bash
podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm linux-builder
```

Build one individual language (replace `ja` with any supported language code):

```bash
WIKI_EDITION=ja podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm linux-builder
```

Build the multilingual edition and all 12 individual editions in one invocation:

```bash
WIKI_EDITION=all podman compose \
  --profile tools \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  run --rm linux-builder
```

To preview one language directly from the source tree without packaging it, derive a temporary
content directory and point Electron at it:

```bash
node scripts/prepare-edition.mjs \
  .local-data/snapshots/<snapshot-id>/content \
  .local-data/editions/es/content \
  es

env -u ELECTRON_RUN_AS_NODE \
  WIKI_EDITION=es \
  WIKI_CONTENT_PATH="$PWD/.local-data/editions/es/content" \
  npm start
```

Replace `<snapshot-id>` with the `snapshot_id` stored in `.local-data/current.json`. The generated
edition directory uses hard links when the filesystem permits it, so staging it is quick and does
not initially duplicate the physical bytes of shared files.

The builder extracts the selected candidate and sets `WIKI_CONTENT_PATH` before invoking Electron
Forge. This embeds the immutable content directory in ZIP, DEB and RPM packages. Official Windows packages are
built from the same snapshot in GitHub Actions. The draft workflow produces the multilingual
artifact plus an individual artifact for every supported language on both operating systems.

Running `npm run make` manually without `WIKI_CONTENT_PATH` is a developer build and may not contain
offline content. Use the provided builder for release packages.

## Scheduling

When scheduling is enabled, the worker uses `America/Chicago`:

- Incremental synchronization: Sunday at 03:00.
- Full reconciliation: day 1 of every month at 03:00.

Only one job may be queued or running at a time. Scheduling and individual languages can be disabled
from the dashboard.

## Stop and restart

Stop containers without deleting local data:

```bash
podman compose \
  --env-file .env.local \
  -f compose.yml \
  -f compose.local.yml \
  down
```

Do not add `-v` unless you intentionally want to delete named volumes. Removing `.local-data/`
deletes snapshots, candidates, runs and audit history.

## Tests

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
npm ci
npm test
```

## Release and production safety

Follow the complete [production and release runbook](docs/production-release-runbook.md) before
configuring GitHub, publishing a snapshot, deploying through the broker, or creating `v2.0.0`.

The rollout has separate approval gates:

1. Validate a candidate locally.
2. Build and test a GitHub draft release.
3. Manually approve the protected `production` deployment.

Nothing in the local workflow pushes a branch, publishes a GitHub release or deploys production.
Production uses an approved snapshot published separately as an immutable OCI artifact.

See:

- [Local testing](docs/local-testing.md)
- [Architecture](docs/architecture.md)
- [Production deployment](docs/production-deployment.md)
- [Repository migration](docs/repository-migration.md)

## Historical releases and repository migration

The repository is kept in place so existing commits, issues, tags and releases remain available.
Generated mirror files can be removed from the current branch through a normal commit without
rewriting history. A complete Git clone will still contain the old history; a shallow clone avoids
downloading unrelated historical objects.

## Licensing

Project code is MIT licensed; see [LICENSE](LICENSE).

Mirrored wiki content is separately licensed under CC BY-NC-SA 3.0; see
[CONTENT-LICENSE.md](CONTENT-LICENSE.md). Application releases and snapshots must remain
noncommercial and retain the required attribution.
