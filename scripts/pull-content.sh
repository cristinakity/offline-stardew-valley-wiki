#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
lock_file="${CONTENT_LOCK_FILE:-$repo_root/content-lock.json}"
data_dir="${DATA_DIR:-$repo_root/.local-data}"
python_bin="${PYTHON_BIN:-python3}"
if [[ -x "$repo_root/.venv/bin/python" && -z "${PYTHON_BIN:-}" ]]; then
  python_bin="$repo_root/.venv/bin/python"
fi

command -v jq >/dev/null || { echo "jq is required." >&2; exit 1; }
command -v oras >/dev/null || { echo "oras is required." >&2; exit 1; }

reference="$(jq -er '.oci_ref | select(type == "string" and test("^ghcr\\.io/.+@sha256:[0-9a-f]{64}$"))' "$lock_file")" || {
  echo "content-lock.json does not contain a published immutable oci_ref yet." >&2
  exit 1
}
archive_name="$(jq -er '.archive_name' "$lock_file")"
expected_sha="$(jq -er '.archive_sha256' "$lock_file")"
temporary="$(mktemp -d)"
trap 'rm -rf -- "$temporary"' EXIT

oras pull "$reference" -o "$temporary"
archive="$temporary/$archive_name"
test -f "$archive"
printf '%s  %s\n' "$expected_sha" "$archive" | sha256sum --check --status

APP_ENV=local DATA_DIR="$data_dir" BIND_HOST=127.0.0.1 \
  "$python_bin" -m wiki_updater.cli snapshot-import --archive "$archive"
echo "Imported approved snapshot into $data_dir"
