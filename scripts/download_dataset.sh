#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
config_file="$repo_root/config/dataset.env"

if [[ -f "$config_file" ]]; then
  # shellcheck disable=SC1090
  source "$config_file"
fi

dataset_url="${FVS_DATASET_URL:-REPLACE_BEFORE_RELEASE}"
dataset_sha256="${FVS_DATASET_SHA256:-REPLACE_BEFORE_RELEASE}"
archive_name="${FVS_DATASET_ARCHIVE:-yfcc_course_v1.tar.zst}"
dataset_parent="${FVS_DATASET_PARENT:-$repo_root/datasets}"
dataset_dir="$dataset_parent/yfcc_course_v1"
archive_path="$dataset_parent/$archive_name"

if [[ "$dataset_url" == "REPLACE_BEFORE_RELEASE" || \
      "$dataset_sha256" == "REPLACE_BEFORE_RELEASE" ]]; then
  echo "ERROR: dataset URL/SHA-256 has not been configured." >&2
  echo "Edit config/dataset.env or set FVS_DATASET_URL and FVS_DATASET_SHA256." >&2
  exit 2
fi

for command_name in curl sha256sum tar; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $command_name" >&2
    exit 2
  fi
done

if [[ -d "$dataset_dir" ]]; then
  echo "Dataset directory already exists; verifying instead of overwriting."
  "$script_dir/check_dataset.sh" "$dataset_dir"
  exit 0
fi

mkdir -p "$dataset_parent"

if [[ -f "$archive_path" ]]; then
  if (cd "$dataset_parent" && printf '%s  %s\n' "$dataset_sha256" "$archive_name" | sha256sum -c -); then
    echo "Reusing verified archive: $archive_path"
  else
    echo "Existing archive is incomplete or invalid; resuming download."
    curl --fail --location --continue-at - "$dataset_url" --output "$archive_path"
  fi
else
  curl --fail --location "$dataset_url" --output "$archive_path"
fi

(cd "$dataset_parent" && printf '%s  %s\n' "$dataset_sha256" "$archive_name" | sha256sum -c -)

case "$archive_name" in
  *.tar.zst) tar --zstd -xf "$archive_path" -C "$dataset_parent" ;;
  *.tar.gz|*.tgz) tar -xzf "$archive_path" -C "$dataset_parent" ;;
  *)
    echo "ERROR: unsupported archive type: $archive_name" >&2
    exit 2
    ;;
esac

"$script_dir/check_dataset.sh" "$dataset_dir"
echo "Dataset ready: $dataset_dir"

