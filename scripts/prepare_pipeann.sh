#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
versions_file="$repo_root/adapters/versions.json"
source_dir="${1:-$repo_root/systems/PipeANN}"
build_jobs="${FVS_BUILD_JOBS:-8}"

repository="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pipeann"]["repository"])' "$versions_file")"
expected_commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pipeann"]["commit"])' "$versions_file")"

for command_name in git cmake python3; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $command_name" >&2
    exit 2
  fi
done

if [[ ! -e "$source_dir" ]]; then
  mkdir -p "$(dirname "$source_dir")"
  git clone "$repository" "$source_dir"
elif [[ ! -d "$source_dir/.git" ]]; then
  echo "ERROR: existing path is not a Git repository: $source_dir" >&2
  exit 2
fi

actual_commit="$(git -C "$source_dir" rev-parse HEAD)"
if [[ "$actual_commit" != "$expected_commit" ]]; then
  if [[ -n "$(git -C "$source_dir" status --porcelain)" ]]; then
    echo "ERROR: $source_dir has local changes; refusing to switch commits." >&2
    exit 2
  fi
  git -C "$source_dir" fetch origin
  git -C "$source_dir" checkout "$expected_commit"
fi

cmake -S "$source_dir" -B "$source_dir/build" -DCMAKE_BUILD_TYPE=Release -DIO_ENGINE=aio -DUSE_TCMALLOC=ON
cmake --build "$source_dir/build" --target build_disk_index_filtered search_disk_index_filtered -j "$build_jobs"

dataset_root="$repo_root/datasets/yfcc_course_v1"
if [[ -d "$dataset_root" ]]; then
  python3 "$repo_root/adapters/pipeann_adapter.py" doctor --repo "$source_dir" --dataset-root "$dataset_root" --tier debug
else
  echo "PipeANN build complete. Download the course dataset before running doctor."
fi
