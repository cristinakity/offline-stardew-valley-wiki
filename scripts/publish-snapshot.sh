#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 CANDIDATE_ARCHIVE OCI_REFERENCE" >&2
  exit 2
fi

archive="$1"
reference="$2"
if [[ ! -f "$archive" ]]; then
  echo "Candidate archive not found: $archive" >&2
  exit 1
fi
if [[ "$reference" != ghcr.io/*:* ]]; then
  echo "OCI reference must be a tagged ghcr.io reference." >&2
  exit 1
fi

oras push "$reference" \
  --artifact-type application/vnd.offline-stardew-valley-wiki.snapshot.v1 \
  "$archive:application/vnd.offline-stardew-valley-wiki.snapshot.layer.v1+zstd"
oras resolve "$reference"
