#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

pipeann_repo="${1:-$repo_root/systems/PipeANN}"
gateann_repo="${2:-$repo_root/systems/GateANN-public}"
run_root="${3:-$repo_root/course_runs}"
dataset_root="${FVS_DATASET_ROOT:-$repo_root/datasets/yfcc_course_v1}"
run_id="${FVS_DEBUG_RUN_ID:-debug-check-$(date +%Y%m%d-%H%M%S)}"

python3 "$repo_root/adapters/pipeann_adapter.py" doctor \
  --repo "$pipeann_repo" --dataset-root "$dataset_root" --tier debug
python3 "$repo_root/adapters/gateann_adapter.py" doctor \
  --repo "$gateann_repo" --dataset-root "$dataset_root" --tier debug

python3 "$repo_root/adapters/pipeann_adapter.py" search \
  --repo "$pipeann_repo" --dataset-root "$dataset_root" \
  --tier debug --run-root "$run_root" --bucket high \
  --threads 1 --beamwidth 8 --k 10 --L 40 --run-id "$run_id"

python3 "$repo_root/adapters/gateann_adapter.py" search \
  --repo "$gateann_repo" --dataset-root "$dataset_root" \
  --tier debug --run-root "$run_root" --bucket high \
  --threads 1 --beamwidth 8 --k 10 --L 320 --run-id "$run_id"

python3 "$repo_root/scripts/check_debug_results.py" \
  --run-root "$run_root" --run-id "$run_id"

echo "Debug validation artifacts: $run_root/results/*/debug_100000/high/$run_id"
