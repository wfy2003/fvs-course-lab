#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
dataset_dir="${1:-$repo_root/datasets/yfcc_course_v1}"

if [[ ! -f "$dataset_dir/checksums.sha256" ]]; then
  echo "ERROR: checksums file not found: $dataset_dir/checksums.sha256" >&2
  exit 2
fi

(cd "$dataset_dir" && sha256sum -c checksums.sha256)
echo "Dataset verification passed: $dataset_dir"

