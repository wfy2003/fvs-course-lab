#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

# shellcheck disable=SC1091
source "$repo_root/config/experiments.env"

pipeann_repo="${1:-$repo_root/systems/PipeANN}"
gateann_repo="${2:-$repo_root/systems/GateANN-public}"
run_root="${3:-$repo_root/course_runs}"
dataset_root="${FVS_DATASET_ROOT:-$repo_root/datasets/yfcc_course_v1}"
experiment_id="${FVS_EXPERIMENT_ID:-$(date +%Y%m%d-%H%M%S)}"

if ! [[ "$FVS_REPEATS" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: FVS_REPEATS must be a positive integer." >&2
  exit 2
fi

read -r -a pipeann_high_l <<<"$FVS_PIPEANN_HIGH_L"
read -r -a gateann_high_l <<<"$FVS_GATEANN_HIGH_L"

"$script_dir/check_dataset.sh" "$dataset_root"
"$script_dir/check_indexes.sh" "$run_root/indices" all

python3 "$repo_root/adapters/pipeann_adapter.py" doctor --repo "$pipeann_repo" --dataset-root "$dataset_root" --tier formal
python3 "$repo_root/adapters/gateann_adapter.py" doctor --repo "$gateann_repo" --dataset-root "$dataset_root" --tier formal

experiment_dir="$run_root/experiments/$experiment_id"
mkdir -p "$experiment_dir"
{
  printf 'experiment_id=%s\n' "$experiment_id"
  printf 'repeats=%s\n' "$FVS_REPEATS"
  printf 'threads=%s\n' "$FVS_THREADS"
  printf 'beamwidth=%s\n' "$FVS_BEAMWIDTH"
  printf 'topk=%s\n' "$FVS_TOPK"
  printf 'pipeann_high_l=%s\n' "$FVS_PIPEANN_HIGH_L"
  printf 'pipeann_representative_l=%s\n' "$FVS_PIPEANN_REPRESENTATIVE_L"
  printf 'gateann_high_l=%s\n' "$FVS_GATEANN_HIGH_L"
  printf 'gateann_representative_l=%s\n' "$FVS_GATEANN_REPRESENTATIVE_L"
  printf 'io_backend=aio\n'
  printf 'pipeann_repo=%s\n' "$pipeann_repo"
  printf 'pipeann_commit=%s\n' "$(git -C "$pipeann_repo" rev-parse HEAD)"
  printf 'gateann_repo=%s\n' "$gateann_repo"
  printf 'gateann_commit=%s\n' "$(git -C "$gateann_repo" rev-parse HEAD)"
  printf 'gateann_patch_sha256='
  sha256sum "$repo_root/patches/gateann_aio_compat.patch"
  printf '\n[uname]\n'
  uname -a
  if command -v lscpu >/dev/null 2>&1; then
    printf '\n[lscpu]\n'
    lscpu
  fi
  if command -v free >/dev/null 2>&1; then
    printf '\n[memory]\n'
    free -h
  fi
  if command -v lsblk >/dev/null 2>&1; then
    printf '\n[block-devices]\n'
    lsblk -d -o NAME,MODEL,SIZE,ROTA,TRAN
  fi
  if command -v c++ >/dev/null 2>&1; then
    printf '\n[compiler]\n'
    c++ --version
  fi
} >"$experiment_dir/environment.txt"

common=(--dataset-root "$dataset_root" --tier formal --run-root "$run_root" --threads "$FVS_THREADS" --beamwidth "$FVS_BEAMWIDTH" --k "$FVS_TOPK")

for repeat in $(seq 1 "$FVS_REPEATS"); do
  run_id="$experiment_id-r$repeat"
  echo "=== Formal repeat $repeat/$FVS_REPEATS: $run_id ==="

  python3 "$repo_root/adapters/pipeann_adapter.py" search --repo "$pipeann_repo" "${common[@]}" --bucket high --L "${pipeann_high_l[@]}" --run-id "$run_id"
  python3 "$repo_root/adapters/pipeann_adapter.py" search --repo "$pipeann_repo" "${common[@]}" --bucket medium --L "$FVS_PIPEANN_REPRESENTATIVE_L" --run-id "$run_id"
  python3 "$repo_root/adapters/pipeann_adapter.py" search --repo "$pipeann_repo" "${common[@]}" --bucket low --L "$FVS_PIPEANN_REPRESENTATIVE_L" --run-id "$run_id"

  python3 "$repo_root/adapters/gateann_adapter.py" search --repo "$gateann_repo" "${common[@]}" --bucket high --L "${gateann_high_l[@]}" --full-adj-neighbors 32 --run-id "$run_id"
  python3 "$repo_root/adapters/gateann_adapter.py" search --repo "$gateann_repo" "${common[@]}" --bucket medium --L "$FVS_GATEANN_REPRESENTATIVE_L" --full-adj-neighbors 32 --run-id "$run_id"
  python3 "$repo_root/adapters/gateann_adapter.py" search --repo "$gateann_repo" "${common[@]}" --bucket low --L "$FVS_GATEANN_REPRESENTATIVE_L" --full-adj-neighbors 32 --run-id "$run_id"
done

python3 "$repo_root/scripts/collect_results.py" \
  --run-root "$run_root" \
  --experiment-id "$experiment_id" \
  --repeats "$FVS_REPEATS" \
  --output "$experiment_dir/results.csv"

echo "Formal experiments complete: $run_root/results"
echo "Aggregated results: $experiment_dir/results.csv"
echo "Experiment metadata: $experiment_dir/environment.txt"
