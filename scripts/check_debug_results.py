#!/usr/bin/env python3
"""Check the two required systems' Debug correctness results."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


EXPECTED = {
    "pipeann": {"L": 40},
    "gateann": {"L": 320},
}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--run-root", type=Path, default=Path("course_runs"))
    result.add_argument("--run-id", default="debug-check")
    result.add_argument("--minimum-recall", type=float, default=80.0)
    return result


def check_one(run_root: Path, run_id: str, system: str, expected_l: int, minimum: float) -> None:
    result_dir = run_root / "results" / system / "debug_100000" / "high" / run_id
    csv_path = result_dir / "results.csv"
    command_path = result_dir / "command.json"
    log_path = result_dir / "run.log"
    for path in (csv_path, command_path, log_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(path)

    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"{csv_path}: expected 1 row, found {len(rows)}")
    row = rows[0]
    expected_values = {
        "system": system,
        "tier": "debug_100000",
        "bucket": "high",
        "queries": "200",
        "L": str(expected_l),
        "k": "10",
        "threads": "1",
        "beamwidth": "8",
    }
    for field, expected in expected_values.items():
        if row.get(field) != expected:
            raise ValueError(
                f"{csv_path}: {field}={row.get(field)!r}, expected {expected!r}"
            )
    recall = float(row["recall_percent"])
    if not minimum <= recall <= 100.0:
        raise ValueError(
            f"{csv_path}: Recall@10={recall:.2f}% is below {minimum:.2f}%"
        )
    command = json.loads(command_path.read_text(encoding="utf-8"))
    if command.get("exit_code") != 0:
        raise ValueError(f"{command_path}: query did not exit successfully")
    print(f"PASS {system}: 200 queries, L={expected_l}, Recall@10={recall:.2f}%")


def main() -> int:
    args = parser().parse_args()
    if not 0.0 <= args.minimum_recall <= 100.0:
        raise ValueError("--minimum-recall must be between 0 and 100")
    run_root = args.run_root.resolve()
    for system, expected in EXPECTED.items():
        check_one(run_root, args.run_id, system, expected["L"], args.minimum_recall)
    print("DEBUG CORRECTNESS CHECK PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
