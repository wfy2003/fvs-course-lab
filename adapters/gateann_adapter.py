#!/usr/bin/env python3
"""Course build/search adapter for GateANN's official artifact."""

from __future__ import annotations

import argparse
from pathlib import Path

from _common import (
    add_build_arguments,
    add_common_arguments,
    add_search_arguments,
    doctor,
    expected_index_prefix,
    main_guard,
    numeric_rows,
    resolve_tier,
    result_directory,
    run_logged,
    validate_dataset,
    validate_positive,
    write_results,
)


SYSTEM = "gateann"


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description="GateANN course adapter")
    sub = top.add_subparsers(dest="action", required=True)
    doctor_parser = sub.add_parser("doctor")
    add_common_arguments(doctor_parser)
    build_parser = sub.add_parser("build")
    add_build_arguments(build_parser)
    build_parser.add_argument("--pq-bytes", type=int, default=32)
    build_parser.add_argument("--merge-memory-gb", type=int, default=8)
    search_parser = sub.add_parser("search")
    add_search_arguments(search_parser)
    search_parser.add_argument("--full-adj-neighbors", type=int, default=32)
    search_parser.add_argument("--mem-L", type=int, default=0)
    search_parser.add_argument("--cache-budget", type=int, default=0)
    return top


def binaries(repo: Path) -> tuple[Path, Path]:
    return (
        repo / "build/tests/build_disk_index",
        repo / "build/tests/search_disk_index_yfcc",
    )


def parse_results(text: str, args: argparse.Namespace) -> list[dict]:
    rows = []
    requested = set(args.L)
    for values in numeric_rows(text, 8):
        if len(values) != 8 or int(values[0]) not in requested:
            continue
        qps = values[1]
        rows.append(
            {
                "L": int(values[0]),
                "k": args.k,
                "threads": args.threads,
                "beamwidth": args.beamwidth,
                "qps": qps,
                "mean_latency_us": 1_000_000.0 / qps if qps else "",
                "recall_percent": values[2] * 100.0,
                "mean_ios": values[3],
                "filter_skips": values[4],
                "io_time_us": values[5],
                "tunnel_time_us": values[6],
                "process_time_us": values[7],
            }
        )
    return rows


def run() -> int:
    args = parser().parse_args()
    repo = args.repo.resolve()
    build_bin, search_bin = binaries(repo)
    if args.action == "doctor":
        return doctor(SYSTEM, args, [build_bin, search_bin])

    tier = resolve_tier(args.dataset_root, args.tier)
    info = validate_dataset(tier, getattr(args, "bucket", None))
    prefix = expected_index_prefix(args, SYSTEM, tier)
    signature = Path(str(prefix) + "_disk.index")

    if args.action == "build":
        validate_positive(args, ["threads", "R", "L_build", "pq_bytes", "merge_memory_gb"])
        if signature.exists():
            if args.reuse_existing:
                print(f"Reusing existing index: {signature}")
                return 0
            raise FileExistsError(
                f"index already exists: {signature}; pass --reuse-existing to keep it"
            )
        command = [
            str(build_bin), "uint8", str(tier / "base.u8bin"), str(prefix),
            str(args.R), str(args.L_build), str(args.pq_bytes),
            str(args.merge_memory_gb), str(args.threads), "l2", "pq",
        ]
        if not args.dry_run:
            prefix.parent.mkdir(parents=True, exist_ok=True)
        build_log = args.run_root.resolve() / "builds" / SYSTEM / tier.name
        run_logged(
            command, build_log,
            {"system": SYSTEM, "tier": tier.name, "dataset": info},
            args.dry_run,
        )
        return 0

    validate_positive(args, ["threads", "beamwidth", "k", "L", "full_adj_neighbors"])
    if args.k > info["ground_truth_k"]:
        raise ValueError(f"k={args.k} exceeds ground-truth k={info['ground_truth_k']}")
    if not signature.is_file() and not args.dry_run:
        raise FileNotFoundError(f"index not found: {signature}; run build first")
    output_dir = result_directory(args, SYSTEM, tier)
    workload = info["workload_dir"]
    command = [
        str(search_bin), "uint8", str(prefix), str(args.threads),
        str(args.beamwidth), str(workload / "query.u8bin"),
        str(tier / "base.metadata.spmat"),
        str(workload / "query.metadata.spmat"),
        str(workload / "ground_truth.ids.ibin"), str(args.k), "l2", "pq",
        "8", str(args.mem_L), str(args.cache_budget),
        str(args.full_adj_neighbors), *map(str, args.L),
    ]
    text = run_logged(
        command, output_dir,
        {"system": SYSTEM, "tier": tier.name, "bucket": args.bucket, "dataset": info},
        args.dry_run,
    )
    if args.dry_run:
        return 0
    rows = parse_results(text, args)
    if len(rows) != len(args.L):
        raise RuntimeError(f"expected {len(args.L)} result rows, parsed {len(rows)}")
    write_results(
        output_dir, SYSTEM, tier.name, args.bucket, workload, rows,
        output_dir / "run.log",
    )
    print(f"Normalized results: {output_dir / 'results.csv'}")
    return 0


if __name__ == "__main__":
    main_guard(run)
