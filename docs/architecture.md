# Architecture

## Components

```text
dashboard/API ── SQLite ── worker/scheduler
                         ├── MediaWiki API and rendered pages
                         ├── content-addressable blob store
                         ├── immutable logical snapshots
                         └── local release candidates

Electron shell ── approved snapshot
GitHub Actions ── OCI snapshot digest ── Linux/Windows draft assets
```

`compose.yml` defines the common image and services. `compose.local.yml` exposes only
`127.0.0.1:8090` by default and bind-mounts `.local-data`. `compose.production.yml` uses named volumes,
GitHub OAuth and a configurable external production network.

## Data layout

```text
/data/
  updater.sqlite3
  blobs/<prefix>/<sha256>.<extension>
  work/<run-id>/
  snapshots/<timestamp-digest>/content/
  candidates/<version>/
  builds/<timestamp>/
  current.json
```

Pages and assets are stored once by digest and hard-linked into snapshots. Three logical snapshots
are retained, and unreferenced CAS blobs are garbage-collected after promotion. A snapshot is
promoted only after exhaustive local link/resource validation. SQLite is backed up daily at 02:30
in the configured timezone, retaining seven copies.

## Synchronization profiles

- `fixture`: deterministic pages and images generated without network access.
- `sample`: first 25 API-enumerated namespace-zero pages for every enabled language.
- `incremental`: enumerate page revisions, hard-link the current snapshot and render only new,
  renamed or changed page IDs; remove deleted page IDs.
- `full`: enumerate and render all namespace-zero pages.

The crawler has a global concurrency ceiling of two HTTP requests and uses exponential retries plus
`Retry-After`. A descriptive User-Agent with contact information is required.

## Normalization

At snapshot time the normalizer:

- Maps local article links to stable page-ID paths.
- Resolves links between language hosts.
- Downloads image `src`, `srcset` and lazy `data-src` values.
- Replaces shared assets with digest-addressed local paths.
- Removes scripts, forms, iframes and edit/login UI; downloads stylesheets and rewrites their
  `url(...)` resources into the digest-addressed asset store.
- Marks external HTTP(S) links for Electron to open through the system browser.

The app never depends on runtime HTML patch injection. This is the regression boundary for issue #5.

## Security boundaries

- Local mode only accepts loopback binding and uses a named development identity.
- Production requires GitHub OAuth, an explicit user allowlist and a 32+ character session secret.
- Electron enables context isolation and sandboxing, disables Node in the renderer and validates all
  local paths exposed by the preload bridge.
- Publication remains disabled in the production API until the GitHub approval integration is
  configured and reviewed.
