#!/usr/bin/env python3
"""Course build/search adapter for legacy C++ Filtered-DiskANN."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from _common import (
    add_build_arguments,
    add_common_arguments,
    add_search_arguments,
    doctor,
    enrich_rows,
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


SYSTEM = "filtered_diskann"
UNLABELED_SENTINEL = "__course_unlabeled_never_query__"


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description="Filtered-DiskANN course adapter")
    sub = top.add_subparsers(dest="action", required=True)
    doctor_parser = sub.add_parser("doctor")
    add_common_arguments(doctor_parser)
    build_parser = sub.add_parser("build")
    add_build_arguments(build_parser)
    build_parser.add_argument("--search-dram-gb", type=float, default=0.25)
    build_parser.add_argument("--build-dram-gb", type=float, default=8.0)
    build_parser.add_argument("--pq-disk-bytes", type=int, default=0)
    search_parser = sub.add_parser("search")
    add_search_arguments(search_parser)
    search_parser.add_argument("--cache-nodes", type=int, default=0)
    search_parser.add_argument("--search-io-limit", type=int, default=None)
    return top


def binaries(repo: Path) -> tuple[Path, Path]:
    return (
        repo / "build/apps/build_disk_index",
        repo / "build/apps/search_disk_index",
    )


def sanitized_label_text(source: Path, expected_rows: int) -> tuple[str, int]:
    rows = source.read_text(encoding="utf-8").splitlines()
    if len(rows) != expected_rows:
        raise ValueError(f"base label row mismatch: {len(rows)} != {expected_rows}")
    replaced = 0
    for index, row in enumerate(rows):
        if not row.strip():
            rows[index] = UNLABELED_SENTINEL
            replaced += 1
    return "\n".join(rows) + "\n", replaced


def query_filter_text(filters_csv: Path, expected_rows: int) -> str:
    labels = []
    with filters_csv.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            labels.append(row["label_id"])
    if len(labels) != expected_rows:
        raise ValueError(f"query filter row mismatch: {len(labels)} != {expected_rows}")
    if any("," in label or not label for label in labels):
        raise ValueError("Filtered-DiskANN requires exactly one non-empty label per query")
    return "\n".join(labels) + "\n"


def parse_results(text: str, args: argparse.Namespace) -> list[dict]:
    rows = []
    requested = set(args.L)
    for values in numeric_rows(text, 9):
        if len(values) != 9 or int(values[0]) not in requested:
            continue
        rows.append(
            {
                "L": int(values[0]),
                "k": args.k,
                "threads": args.threads,
                "beamwidth": int(values[1]),
                "qps": values[2],
                "mean_latency_us": values[3],
                "p999_latency_us": values[4],
                "mean_ios": values[5],
                "io_time_us": values[6],
                "recall_percent": values[8],
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
    diskann_labels = prefix.parent / "base.labels.diskann.txt"

    if args.action == "build":
        validate_positive(args, ["threads", "R", "L_build", "search_dram_gb", "build_dram_gb"])
        if args.pq_disk_bytes < 0:
            raise ValueError("--pq-disk-bytes cannot be negative")
        if signature.exists():
            if args.reuse_existing:
                print(f"Reusing existing index: {signature}")
                return 0
            raise FileExistsError(
                f"index already exists: {signature}; pass --reuse-existing to keep it"
            )
        label_text, replaced = sanitized_label_text(
            tier / "base.labels.txt", info["base_size"]
        )
        command = [
            str(build_bin),
            "--data_type", "uint8",
            "--dist_fn", "l2",
            "--data_path", str(tier / "base.u8bin"),
            "--index_path_prefix", str(prefix),
            "-R", str(args.R),
            "-L", str(args.L_build),
            "--FilteredLbuild", str(args.L_build),
            "-B", str(args.search_dram_gb),
            "-M", str(args.build_dram_gb),
            "-T", str(args.threads),
            "--PQ_disk_bytes", str(args.pq_disk_bytes),
            "--label_type", "uint",
            "--label_file", str(diskann_labels),
        ]
        if not args.dry_run:
            prefix.parent.mkdir(parents=True, exist_ok=True)
            diskann_labels.write_text(label_text, encoding="utf-8")
        build_log = args.run_root.resolve() / "builds" / SYSTEM / tier.name
        run_logged(
            command, build_log,
            {
                "system": SYSTEM,
                "tier": tier.name,
                "dataset": info,
                "unlabeled_rows_assigned_sentinel": replaced,
                "unlabeled_sentinel": UNLABELED_SENTINEL,
            },
            args.dry_run,
        )
        if args.dry_run:
            print(f"Label sanitization would replace {replaced} empty rows.")
        return 0

    validate_positive(args, ["threads", "beamwidth", "k", "L"])
    if args.cache_nodes < 0:
        raise ValueError("--cache-nodes cannot be negative")
    if args.search_io_limit is not None and args.search_io_limit <= 0:
        raise ValueError("--search-io-limit must be positive")
    if args.k > info["ground_truth_k"]:
        raise ValueError(f"k={args.k} exceeds ground-truth k={info['ground_truth_k']}")
    if not signature.is_file() and not args.dry_run:
        raise FileNotFoundError(f"index not found: {signature}; run build first")
    output_dir = result_directory(args, SYSTEM, tier)
    workload = info["workload_dir"]
    filters_text = query_filter_text(
        workload / "query_filters.csv", info["query_count"]
    )
    filters_path = output_dir / "query_filters.txt"
    result_prefix = output_dir / "result"
    command = [
        str(search_bin),
        "--data_type", "uint8",
        "--dist_fn", "l2",
        "--index_path_prefix", str(prefix),
        "--query_file", str(workload / "query.u8bin"),
        "--gt_file", str(workload / "ground_truth.diskann.bin"),
        "--query_filters_file", str(filters_path),
        "--label_type", "uint",
        "-K", str(args.k),
        "-L", *map(str, args.L),
        "-W", str(args.beamwidth),
        "-T", str(args.threads),
        "--num_nodes_to_cache", str(args.cache_nodes),
        "--result_path", str(result_prefix),
    ]
    if args.search_io_limit is not None:
        command.extend(["--search_io_limit", str(args.search_io_limit)])
    text = run_logged(
        command, output_dir,
        {"system": SYSTEM, "tier": tier.name, "bucket": args.bucket, "dataset": info},
        args.dry_run,
        {"query_filters.txt": filters_text},
    )
    if args.dry_run:
        print(f"Generated {info['query_count']} one-label query filters.")
        return 0
    rows = parse_results(text, args)
    if len(rows) != len(args.L):
        raise RuntimeError(f"expected {len(args.L)} result rows, parsed {len(rows)}")
    enrich_rows(rows, repo, prefix, output_dir)
    write_results(
        output_dir, SYSTEM, tier.name, args.bucket, workload, rows,
        output_dir / "run.log",
    )
    print(f"Normalized results: {output_dir / 'results.csv'}")
    return 0


if __name__ == "__main__":
    main_guard(run)
