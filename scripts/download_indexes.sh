#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
config_file="$repo_root/config/indexes.env"

# shellcheck disable=SC1090
source "$config_file"

index_root="${FVS_INDEX_ROOT:-$repo_root/course_runs/indices}"
download_dir="${FVS_INDEX_DOWNLOAD_DIR:-$index_root/downloads}"

for command_name in curl sha256sum tar zstd mktemp python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $command_name" >&2
    exit 2
  fi
done

download_one() {
  local system="$1"
  local url="$2"
  local expected_sha="$3"
  local archive_name="$4"
  local archive_topdir="$5"
  local target_dir="$index_root/$system/formal_1000000"
  local archive_path="$download_dir/$archive_name"

  if [[ -d "$target_dir" ]]; then
    echo "Index directory already exists; verifying instead of overwriting: $target_dir"
    "$script_dir/check_indexes.sh" "$index_root" "$system"
    return
  fi

  mkdir -p "$download_dir"
  if [[ -f "$archive_path" ]]; then
    if (cd "$download_dir" && printf '%s  %s\n' "$expected_sha" "$archive_name" | sha256sum -c -); then
      echo "Reusing verified archive: $archive_path"
    else
      echo "Existing archive is incomplete or invalid; resuming download."
      curl --fail --location --continue-at - "$url" --output "$archive_path"
    fi
  else
    curl --fail --location "$url" --output "$archive_path"
  fi

  (cd "$download_dir" && printf '%s  %s\n' "$expected_sha" "$archive_name" | sha256sum -c -)

  local extract_dir
  extract_dir="$(mktemp -d "$index_root/.extract-$system.XXXXXX")"
  tar --zstd -xf "$archive_path" -C "$extract_dir"
  if [[ ! -d "$extract_dir/$archive_topdir" ]]; then
    echo "ERROR: archive does not contain expected directory: $archive_topdir" >&2
    exit 2
  fi
  mkdir -p "$(dirname "$target_dir")"
  mv "$extract_dir/$archive_topdir" "$target_dir"
  rmdir "$extract_dir"
  "$script_dir/check_indexes.sh" "$index_root" "$system"
}

download_one pipeann "$FVS_PIPEANN_INDEX_URL" "$FVS_PIPEANN_INDEX_SHA256" "$FVS_PIPEANN_INDEX_ARCHIVE" "$FVS_PIPEANN_INDEX_TOPDIR"

download_one gateann "$FVS_GATEANN_INDEX_URL" "$FVS_GATEANN_INDEX_SHA256" "$FVS_GATEANN_INDEX_ARCHIVE" "$FVS_GATEANN_INDEX_TOPDIR"

echo "Both formal indexes are ready under: $index_root"
