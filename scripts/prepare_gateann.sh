#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
versions_file="$repo_root/adapters/versions.json"
patch_file="$repo_root/patches/gateann_aio_compat.patch"
source_dir="${1:-$repo_root/systems/GateANN-public}"
build_jobs="${FVS_BUILD_JOBS:-8}"

repository="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["gateann"]["repository"])' "$versions_file")"
expected_commit="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["gateann"]["commit"])' "$versions_file")"

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

if git -C "$source_dir" apply --reverse --check "$patch_file" >/dev/null 2>&1; then
  echo "GateANN AIO compatibility patch is already applied."
elif git -C "$source_dir" apply --check "$patch_file"; then
  git -C "$source_dir" apply "$patch_file"
  echo "Applied GateANN AIO compatibility patch."
else
  echo "ERROR: GateANN compatibility patch does not apply cleanly." >&2
  exit 2
fi

cmake -S "$source_dir" -B "$source_dir/build" -DCMAKE_BUILD_TYPE=Release -DUSE_AIO=ON
cmake --build "$source_dir/build" --target build_disk_index search_disk_index_yfcc -j "$build_jobs"

dataset_root="$repo_root/datasets/yfcc_course_v1"
if [[ -d "$dataset_root" ]]; then
  python3 "$repo_root/adapters/gateann_adapter.py" doctor --repo "$source_dir" --dataset-root "$dataset_root" --tier debug
else
  echo "GateANN build complete. Download the course dataset before running doctor."
fi
