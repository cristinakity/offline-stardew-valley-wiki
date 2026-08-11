#!/usr/bin/env bash
set -euo pipefail

data_dir="${DATA_DIR:-/data}"
output_dir="${BUILD_OUTPUT_DIR:-$data_dir/builds}"
current_file="$data_dir/current.json"
candidate_version="${CANDIDATE_VERSION:-}"
requested_edition="${WIKI_EDITION:-multilingual}"
supported_languages=(en es de fr it ja ko hu pt ru tr zh)

if [[ ! -f "$current_file" ]]; then
  echo "No current snapshot. Run or import a synchronization first." >&2
  exit 1
fi

snapshot_path="$(node -e "const fs=require('fs');console.log(JSON.parse(fs.readFileSync(process.argv[1],'utf8')).path)" "$current_file")"
source_content="$snapshot_path/content"
snapshot_id="$(basename "$snapshot_path")"
if [[ ! -d "$source_content" ]]; then
  echo "Snapshot content directory does not exist: $source_content" >&2
  exit 1
fi

case "$requested_edition" in
  all) editions=(multilingual "${supported_languages[@]}") ;;
  multilingual|full) editions=(multilingual) ;;
  *)
    if [[ ! " ${supported_languages[*]} " =~ " $requested_edition " ]]; then
      echo "Unsupported WIKI_EDITION: $requested_edition" >&2
      echo "Use multilingual (or full), all, or one of: ${supported_languages[*]}" >&2
      exit 1
    fi
    editions=("$requested_edition")
    ;;
esac

mkdir -p "$output_dir"
npm ci
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="$output_dir/$timestamp"
mkdir -p "$destination"

for edition in "${editions[@]}"; do
  if [[ "$edition" == multilingual ]]; then
    edition_content="$source_content"
  else
    edition_content="$output_dir/.editions/$snapshot_id/$edition/content"
    node scripts/prepare-edition.mjs "$source_content" "$edition_content" "$edition"
  fi

  echo "Building Linux edition: $edition"
  rm -rf /workspace/out
  WIKI_CONTENT_PATH="$edition_content" WIKI_EDITION="$edition" npm run make:linux
  find out/make -type f \( -name '*.zip' -o -name '*.deb' -o -name '*.rpm' \) -exec cp '{}' "$destination" \;
done

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
