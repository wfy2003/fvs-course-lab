#!/usr/bin/env python3
"""Course build/search adapter for PipeANN-Filter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _common import (
    add_build_arguments,
    add_common_arguments,
    add_search_arguments,
    begin_index_build,
    doctor,
    enrich_rows,
    expected_index_prefix,
    finish_index_build,
    main_guard,
    numeric_rows,
    preserve_failed_index_build,
    resolve_tier,
    result_directory,
    run_logged,
    validate_dataset,
    validate_positive,
    write_results,
)


SYSTEM = "pipeann"


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description="PipeANN-Filter course adapter")
    sub = top.add_subparsers(dest="action", required=True)
    doctor_parser = sub.add_parser("doctor")
    add_common_arguments(doctor_parser)
    build_parser = sub.add_parser("build")
    add_build_arguments(build_parser)
    build_parser.add_argument("--R-dense", type=int, default=256)
    build_parser.add_argument("--pq-bytes", type=int, default=32)
    build_parser.add_argument("--build-memory-gb", type=int, default=8)
    search_parser = sub.add_parser("search")
    add_search_arguments(search_parser)
    search_parser.add_argument("--mem-L", type=int, default=0)
    return top


def binaries(repo: Path) -> tuple[Path, Path]:
    return (
        repo / "build/tests/build_disk_index_filtered",
        repo / "build/tests/search_disk_index_filtered",
    )


def parse_results(text: str, args: argparse.Namespace) -> list[dict]:
    rows = []
    requested = set(args.L)
    for values in numeric_rows(text, 6):
        if int(values[0]) not in requested or int(values[1]) != args.beamwidth:
            continue
        rows.append(
            {
                "L": int(values[0]),
                "k": args.k,
                "threads": args.threads,
                "beamwidth": int(values[1]),
                "qps": values[2],
                "mean_latency_us": values[3],
                "mean_ios": values[-2],
                "recall_percent": values[-1],
                "pre_filter_queries": values[4],
                "in_filter_queries": values[10],
                "post_filter_queries": values[16],
                "filter_false_positives": values[8] + values[14] + values[20],
            }
        )
    return rows


def run() -> int:
    args = parser().parse_args()
    repo = args.repo.resolve()
    build_bin, search_bin = binaries(repo)
    if args.action == "doctor":
        return doctor(
            SYSTEM,
            args,
            [build_bin, search_bin],
            {"CMAKE_BUILD_TYPE": "Release", "IO_ENGINE": "aio"},
        )

    tier = resolve_tier(args.dataset_root, args.tier)
    info = validate_dataset(tier, getattr(args, "bucket", None))
    prefix = expected_index_prefix(args, SYSTEM, tier)
    signature = Path(str(prefix) + "_disk.index")

    if args.action == "build":
        validate_positive(args, ["threads", "R", "R_dense", "L_build", "pq_bytes", "build_memory_gb"])
        attempt = begin_index_build(args, SYSTEM, tier)
        if attempt is None:
            return 0
        command = [
            str(build_bin), "uint8", str(tier / "base.u8bin"), str(attempt.staging_prefix),
            str(args.R), str(args.R_dense), str(args.L_build), str(args.pq_bytes),
            str(args.build_memory_gb), str(args.threads), "l2", "pq",
            "label_spmat", str(tier / "base.metadata.spmat"),
        ]
        try:
            run_logged(
                command,
                attempt.log_directory,
                {
                    "system": SYSTEM,
                    "tier": tier.name,
                    "dataset": info,
                    "build_attempt": attempt.attempt_id,
                    "final_index_prefix": str(attempt.final_prefix),
                },
                args.dry_run,
            )
            if not args.dry_run:
                finish_index_build(attempt)
        except Exception:
            if not args.dry_run:
                preserve_failed_index_build(attempt)
            raise
        return 0

    validate_positive(args, ["threads", "beamwidth", "k", "L"])
    if args.k > info["ground_truth_k"]:
        raise ValueError(f"k={args.k} exceeds ground-truth k={info['ground_truth_k']}")
    if not signature.is_file() and not args.dry_run:
        raise FileNotFoundError(f"index not found: {signature}; run build first")
    output_dir = result_directory(args, SYSTEM, tier)
    workload = info["workload_dir"]
    config = {
        "attr_indexes": [{
            "name": "tags",
            "key": 0,
            "type": "label",
            "file": str(prefix) + ".label.0",
        }],
        "filter": "array_contains_all(tags, $$query_tags)",
        "bindings": {
            "query_tags": str(workload / "query.metadata.spmat"),
        },
    }
    config_text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    config_path = output_dir / "filter_config.json"
    command = [
        str(search_bin), "uint8", str(prefix), str(args.threads),
        str(args.beamwidth), str(workload / "query.u8bin"),
        str(workload / "ground_truth.diskann.bin"), str(args.k), "l2", "pq",
        str(config_path), str(args.mem_L), *map(str, args.L),
    ]
    text = run_logged(
        command, output_dir,
        {"system": SYSTEM, "tier": tier.name, "bucket": args.bucket, "dataset": info},
        args.dry_run,
        {"filter_config.json": config_text},
    )
    if args.dry_run:
        print("Generated filter config:")
        print(config_text, end="")
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
