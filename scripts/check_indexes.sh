#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
index_root="${1:-$repo_root/course_runs/indices}"
selection="${2:-all}"

verify_index() {
  local system="$1"
  local expected_system="$2"
  local index_dir="$index_root/$system/formal_1000000"

  if [[ ! -d "$index_dir" ]]; then
    echo "ERROR: index directory not found: $index_dir" >&2
    return 2
  fi
  if [[ ! -f "$index_dir/checksums.sha256" || ! -f "$index_dir/manifest.json" ]]; then
    echo "ERROR: index manifest/checksums missing in $index_dir" >&2
    return 2
  fi

  (cd "$index_dir" && sha256sum --quiet -c checksums.sha256)
  python3 - "$index_dir/manifest.json" "$expected_system" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2]
manifest = json.loads(path.read_text(encoding="utf-8"))
if manifest.get("system") != expected:
    raise SystemExit(
        f"ERROR: {path}: system={manifest.get('system')!r}, expected {expected!r}"
    )
if manifest.get("dataset_release") != "dataset-v1.0":
    raise SystemExit(f"ERROR: unexpected dataset release in {path}")
if manifest.get("dataset_tier") != "formal_1000000":
    raise SystemExit(f"ERROR: unexpected dataset tier in {path}")
print(f"Manifest OK: {path}")
PY
  echo "Index verification passed: $index_dir"
}

case "$selection" in
  pipeann)
    verify_index pipeann pipeann-filter
    ;;
  gateann)
    verify_index gateann gateann
    ;;
  all)
    verify_index pipeann pipeann-filter
    verify_index gateann gateann
    ;;
  *)
    echo "Usage: $0 [index-root] [pipeann|gateann|all]" >&2
    exit 2
    ;;
esac
