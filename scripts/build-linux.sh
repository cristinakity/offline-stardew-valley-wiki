#!/usr/bin/env bash
set -euo pipefail

data_dir="${DATA_DIR:-/data}"
output_dir="${BUILD_OUTPUT_DIR:-$data_dir/builds}"
candidate_version="${CANDIDATE_VERSION:-}"
candidate_dir="${CANDIDATE_DIR:-}"
candidate_archive="${CANDIDATE_ARCHIVE:-}"
build_job_id="${BUILD_JOB_ID:-manual}"
requested_edition="${WIKI_EDITION:-multilingual}"
supported_languages=(en es de fr it ja ko hu pt ru tr zh)

if [[ ! "$build_job_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "Unsafe BUILD_JOB_ID: $build_job_id" >&2
  exit 1
fi

if [[ -z "$candidate_archive" ]]; then
  if [[ -z "$candidate_dir" && -n "$candidate_version" ]]; then
    candidate_dir="$data_dir/candidates/$candidate_version"
  fi
  if [[ -z "$candidate_dir" ]]; then
    candidate_dir="$(find "$data_dir/candidates" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -nr | head -n1 | cut -d' ' -f2-)"
  fi
  if [[ -z "$candidate_dir" || ! -d "$candidate_dir" ]]; then
    echo "No candidate exists. Create one before building packages." >&2
    exit 1
  fi
  mapfile -t candidate_archives < <(find "$candidate_dir" -maxdepth 1 -type f -name 'wiki-content-*.tar.zst' -print)
  if [[ "${#candidate_archives[@]}" -ne 1 ]]; then
    echo "Candidate must contain exactly one wiki-content-*.tar.zst archive." >&2
    exit 1
  fi
  candidate_archive="${candidate_archives[0]}"
fi
if [[ ! -f "$candidate_archive" ]]; then
  echo "Candidate archive does not exist: $candidate_archive" >&2
  exit 1
fi

input_root="$data_dir/work/build-$build_job_id"
rm -rf "$input_root"
mkdir -p "$input_root"
trap 'rm -rf "$input_root"' EXIT
echo "Preparing candidate archive: $(basename "$candidate_archive")"
tar --zstd -xf "$candidate_archive" -C "$input_root" content manifest.json
source_content="$input_root/content"
snapshot_id="$(basename "$candidate_archive" .tar.zst)"

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
destination="${BUILD_DESTINATION:-$output_dir/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$destination"

edition_total="${#editions[@]}"
edition_current=0
for edition in "${editions[@]}"; do
  if [[ "$edition" == multilingual ]]; then
    edition_content="$source_content"
  else
    edition_content="$input_root/editions/$edition/content"
    node scripts/prepare-edition.mjs "$source_content" "$edition_content" "$edition"
  fi

  echo "Building Linux edition: $edition"
  rm -rf /workspace/out
  WIKI_CONTENT_PATH="$edition_content" WIKI_EDITION="$edition" npm run make:linux
  find out/make -type f \( -name '*.zip' -o -name '*.deb' -o -name '*.rpm' \) -exec cp '{}' "$destination" \;
  edition_current=$((edition_current + 1))
  echo "BUILD_PROGRESS $edition $edition_current $edition_total"
done

find "$destination" -type f -print0 | sort -z | xargs -0 sha256sum > "$destination/SHA256SUMS"
echo "Linux packages written to $destination"
