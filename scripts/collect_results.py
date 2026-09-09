#!/usr/bin/env python3
"""Collect and validate one formal experiment's normalized CSV files."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


SYSTEMS = ("pipeann", "gateann")
BUCKETS = ("high", "medium", "low")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--run-root", type=Path, default=Path("course_runs"))
    result.add_argument("--experiment-id", required=True)
    result.add_argument("--repeats", type=int, default=3)
    result.add_argument("--output", type=Path, default=None)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.repeats <= 0:
        raise ValueError("--repeats must be positive")
    run_root = args.run_root.resolve()
    output = args.output or run_root / "experiments" / args.experiment_id / "results.csv"

    collected: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    for repeat in range(1, args.repeats + 1):
        run_id = f"{args.experiment_id}-r{repeat}"
        for system in SYSTEMS:
            for bucket in BUCKETS:
                source = (
                    run_root
                    / "results"
                    / system
                    / "formal_1000000"
                    / bucket
                    / run_id
                    / "results.csv"
                )
                if not source.is_file():
                    raise FileNotFoundError(source)
                with source.open(newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    if reader.fieldnames is None:
                        raise ValueError(f"missing CSV header: {source}")
                    if fieldnames is None:
                        fieldnames = list(reader.fieldnames)
                    elif reader.fieldnames != fieldnames:
                        raise ValueError(f"CSV columns differ: {source}")
                    rows = list(reader)
                expected_rows = 3 if bucket == "high" else 1
                if len(rows) != expected_rows:
                    raise ValueError(
                        f"{source}: expected {expected_rows} rows, found {len(rows)}"
                    )
                for row in rows:
                    if row["system"] != system or row["bucket"] != bucket:
                        raise ValueError(f"path/row identity mismatch in {source}")
                    if row["tier"] != "formal_1000000":
                        raise ValueError(f"unexpected tier in {source}")
                    recall = float(row["recall_percent"])
                    if not 0.0 <= recall <= 100.0:
                        raise ValueError(f"invalid Recall in {source}: {recall}")
                    if int(row["queries"]) != 200:
                        raise ValueError(f"unexpected query count in {source}")
                    collected.append({"repeat": str(repeat), "run_id": run_id, **row})

    expected_total = args.repeats * 10
    if len(collected) != expected_total:
        raise ValueError(f"expected {expected_total} rows, found {len(collected)}")
    assert fieldnames is not None
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["repeat", "run_id", *fieldnames])
        writer.writeheader()
        writer.writerows(collected)
    print(f"Collected and validated {len(collected)} rows: {output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
