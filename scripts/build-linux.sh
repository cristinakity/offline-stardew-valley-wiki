#!/usr/bin/env bash
set -euo pipefail

data_dir="${DATA_DIR:-/data}"
output_dir="${BUILD_OUTPUT_DIR:-$data_dir/builds}"
current_file="$data_dir/current.json"
candidate_version="${CANDIDATE_VERSION:-}"

if [[ ! -f "$current_file" ]]; then
  echo "No current snapshot. Run a synchronization first." >&2
  exit 1
fi

snapshot_path="$(node -e "const fs=require('fs');console.log(JSON.parse(fs.readFileSync(process.argv[1],'utf8')).path)" "$current_file")"
export WIKI_CONTENT_PATH="$snapshot_path/content"

if [[ ! -d "$WIKI_CONTENT_PATH" ]]; then
  echo "Snapshot content directory does not exist: $WIKI_CONTENT_PATH" >&2
  exit 1
fi

mkdir -p "$output_dir"
npm ci
npm run make:linux

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$output_dir/$timestamp"
mkdir -p "$destination"
find out/make -type f \( -name '*.zip' -o -name '*.deb' -o -name '*.rpm' \) -exec cp '{}' "$destination" \;
find "$destination" -type f -print0 | sort -z | xargs -0 sha256sum > "$destination/SHA256SUMS"

if [[ -n "$candidate_version" ]]; then
  candidate_dir="$data_dir/candidates/$candidate_version"
else
  candidate_dir="$(find "$data_dir/candidates" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
fi
if [[ -z "${candidate_dir:-}" || ! -d "$candidate_dir" ]]; then
  echo "No candidate exists. Create one before building Linux packages." >&2
  exit 1
fi
find "$destination" -maxdepth 1 -type f \( -name '*.zip' -o -name '*.deb' -o -name '*.rpm' \) -exec cp '{}' "$candidate_dir" \;
find "$candidate_dir" -maxdepth 1 -type f ! -name SHA256SUMS -printf '%f\0' \
  | sort -z \
  | while IFS= read -r -d '' name; do sha256sum "$candidate_dir/$name"; done \
  | sed "s#  $candidate_dir/#  #" > "$candidate_dir/SHA256SUMS"
echo "Linux packages written to $destination"
echo "Candidate assets updated in $candidate_dir"
