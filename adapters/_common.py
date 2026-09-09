#!/usr/bin/env python3
"""Shared validation, execution, and result helpers for course adapters."""

from __future__ import annotations

import argparse
import csv
import json
import os
import resource
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
VERSIONS = json.loads((ROOT / "versions.json").read_text(encoding="utf-8"))
RESULT_COLUMNS = [
    "system",
    "tier",
    "bucket",
    "queries",
    "selectivity_min",
    "selectivity_median",
    "selectivity_max",
    "L",
    "k",
    "threads",
    "beamwidth",
    "system_commit",
    "index_bytes",
    "elapsed_seconds",
    "peak_rss_kb",
    "qps",
    "mean_latency_us",
    "p999_latency_us",
    "recall_percent",
    "mean_ios",
    "pre_filter_queries",
    "in_filter_queries",
    "post_filter_queries",
    "filter_false_positives",
    "filter_skips",
    "io_time_us",
    "tunnel_time_us",
    "process_time_us",
    "raw_log",
]


@dataclass(frozen=True)
class IndexBuildAttempt:
    attempt_id: str
    final_prefix: Path
    staging_prefix: Path
    log_directory: Path


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, required=True, help="system source repository")
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument(
        "--tier",
        default="debug",
        help="debug/formal alias or exact directory name such as debug_100000",
    )
    parser.add_argument("--run-root", type=Path, default=Path("course_runs"))
    parser.add_argument("--dry-run", action="store_true")


def add_build_arguments(parser: argparse.ArgumentParser) -> None:
    add_common_arguments(parser)
    parser.add_argument("--threads", type=int, default=min(os.cpu_count() or 1, 8))
    parser.add_argument("--R", type=int, default=32)
    parser.add_argument("--L-build", type=int, default=64)
    parser.add_argument("--reuse-existing", action="store_true")


def add_search_arguments(parser: argparse.ArgumentParser) -> None:
    add_common_arguments(parser)
    parser.add_argument("--bucket", choices=("low", "medium", "high"), required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--beamwidth", type=int, default=8)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--L", type=int, nargs="+", default=[20, 40, 80])
    parser.add_argument(
        "--run-id",
        default=None,
        help="result directory suffix; defaults to a timestamp",
    )


def validate_positive(args: argparse.Namespace, names: list[str]) -> None:
    for name in names:
        value = getattr(args, name)
        values = value if isinstance(value, list) else [value]
        if any(item <= 0 for item in values):
            raise ValueError(f"--{name.replace('_', '-')} must be positive")


def resolve_tier(dataset_root: Path, requested: str) -> Path:
    dataset_root = dataset_root.resolve()
    exact = dataset_root / requested
    if exact.is_dir():
        return exact
    matches = sorted(path for path in dataset_root.glob(f"{requested}_*") if path.is_dir())
    if len(matches) != 1:
        raise FileNotFoundError(
            f"cannot resolve tier {requested!r} under {dataset_root}; matches={matches}"
        )
    return matches[0]


def read_bin_header(path: Path) -> tuple[int, int]:
    import struct

    with path.open("rb") as handle:
        header = handle.read(8)
    if len(header) != 8:
        raise ValueError(f"invalid binary matrix header: {path}")
    return struct.unpack("<II", header)


def read_spmat_header(path: Path) -> tuple[int, int, int]:
    import struct

    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24:
        raise ValueError(f"invalid spmat header: {path}")
    return struct.unpack("<qqq", header)


def validate_dataset(tier_dir: Path, bucket: str | None = None) -> dict[str, Any]:
    base = tier_dir / "base.u8bin"
    metadata = tier_dir / "base.metadata.spmat"
    labels = tier_dir / "base.labels.txt"
    for path in (base, metadata, labels):
        if not path.is_file():
            raise FileNotFoundError(path)
    n, dim = read_bin_header(base)
    meta_n, meta_cols, meta_nnz = read_spmat_header(metadata)
    if n != meta_n:
        raise ValueError(f"base/metadata row mismatch: {n} != {meta_n}")
    result: dict[str, Any] = {
        "base_size": n,
        "dimension": dim,
        "metadata_columns": meta_cols,
        "metadata_nnz": meta_nnz,
    }
    if bucket is None:
        return result

    workload = tier_dir / "workloads" / bucket
    required = (
        workload / "query.u8bin",
        workload / "query.metadata.spmat",
        workload / "query_filters.csv",
        workload / "labels.csv",
        workload / "ground_truth.ids.ibin",
        workload / "ground_truth.diskann.bin",
    )
    for path in required:
        if not path.is_file():
            raise FileNotFoundError(path)
    nq, qdim = read_bin_header(workload / "query.u8bin")
    gt_nq, gt_k = read_bin_header(workload / "ground_truth.ids.ibin")
    qmeta_nq, qmeta_cols, qmeta_nnz = read_spmat_header(workload / "query.metadata.spmat")
    if not (qdim == dim and nq == gt_nq == qmeta_nq and qmeta_nnz == nq):
        raise ValueError("query, metadata, and ground-truth dimensions are inconsistent")
    if qmeta_cols != meta_cols:
        raise ValueError("base/query metadata columns differ")
    result.update(
        {
            "workload_dir": workload,
            "query_count": nq,
            "ground_truth_k": gt_k,
        }
    )
    return result


def expected_index_prefix(args: argparse.Namespace, system: str, tier_dir: Path) -> Path:
    return (
        args.run_root.resolve()
        / "indices"
        / system
        / tier_dir.name
        / "yfcc"
    )


def begin_index_build(
    args: argparse.Namespace,
    system: str,
    tier_dir: Path,
) -> IndexBuildAttempt | None:
    final_prefix = expected_index_prefix(args, system, tier_dir)
    signature = Path(str(final_prefix) + "_disk.index")
    if signature.is_file():
        if args.reuse_existing:
            print(f"Reusing existing index: {signature}")
            return None
        raise FileExistsError(
            f"index already exists: {signature}; pass --reuse-existing to keep it"
        )

    attempt_id = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    index_parent = final_prefix.parent.parent
    final_directory = final_prefix.parent
    staging_directory = index_parent / f".{tier_dir.name}.building-{attempt_id}"
    attempt = IndexBuildAttempt(
        attempt_id=attempt_id,
        final_prefix=final_prefix,
        staging_prefix=staging_directory / final_prefix.name,
        log_directory=(
            args.run_root.resolve()
            / "builds"
            / system
            / tier_dir.name
            / attempt_id
        ),
    )
    if args.dry_run:
        return attempt

    index_parent.mkdir(parents=True, exist_ok=True)
    if final_directory.exists():
        preserved = index_parent / f".{tier_dir.name}.incomplete-{attempt_id}"
        final_directory.rename(preserved)
        print(f"Preserved incomplete index from an earlier build: {preserved}")

    staging_directory.mkdir(parents=False, exist_ok=False)
    return attempt


def finish_index_build(attempt: IndexBuildAttempt) -> None:
    staging_directory = attempt.staging_prefix.parent
    signature = Path(str(attempt.staging_prefix) + "_disk.index")
    if not signature.is_file():
        raise RuntimeError(f"build exited successfully but index is missing: {signature}")
    if attempt.final_prefix.parent.exists():
        raise FileExistsError(
            f"cannot publish index because target exists: {attempt.final_prefix.parent}"
        )
    staging_directory.rename(attempt.final_prefix.parent)
    print(f"Index ready: {attempt.final_prefix}")


def preserve_failed_index_build(attempt: IndexBuildAttempt) -> None:
    staging_directory = attempt.staging_prefix.parent
    if not staging_directory.exists():
        return
    failed_directory = staging_directory.with_name(
        f".{attempt.final_prefix.parent.name}.failed-{attempt.attempt_id}"
    )
    staging_directory.rename(failed_directory)
    print(
        f"Incomplete index retained for diagnosis: {failed_directory}",
        file=sys.stderr,
    )
    print("Run the same build command again to start a clean retry.", file=sys.stderr)


def result_directory(args: argparse.Namespace, system: str, tier_dir: Path) -> Path:
    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    return (
        args.run_root.resolve()
        / "results"
        / system
        / tier_dir.name
        / args.bucket
        / run_id
    )


def git_revision(repo: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def cmake_cache_values(repo: Path) -> dict[str, str]:
    cache = repo / "build" / "CMakeCache.txt"
    if not cache.is_file():
        return {}
    values: dict[str, str] = {}
    for line in cache.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith(("//", "#")) or ":" not in line or "=" not in line:
            continue
        name_and_type, value = line.split("=", 1)
        name, _cache_type = name_and_type.split(":", 1)
        values[name] = value
    return values


def doctor(
    system: str,
    args: argparse.Namespace,
    binaries: list[Path],
    expected_cmake: dict[str, str] | None = None,
) -> int:
    repo = args.repo.resolve()
    tier = resolve_tier(args.dataset_root, args.tier)
    info = validate_dataset(tier)
    revision = git_revision(repo)
    expected = VERSIONS[system]["commit"]
    print(f"system:           {system}")
    print(f"repository:       {repo}")
    print(f"expected commit:  {expected}")
    print(f"actual commit:    {revision or 'not a git checkout'}")
    print(f"dataset tier:     {tier}")
    print(f"base:             {info['base_size']} x {info['dimension']} uint8")
    missing = [path for path in binaries if not path.is_file() or not os.access(path, os.X_OK)]
    for binary in binaries:
        state = "OK" if binary not in missing else "MISSING"
        print(f"binary [{state}]: {binary}")
    configuration_errors = []
    cache_values = cmake_cache_values(repo)
    for name, expected_value in (expected_cmake or {}).items():
        actual_value = cache_values.get(name)
        state = "OK" if actual_value == expected_value else "MISMATCH"
        print(f"cmake [{state}]:  {name}={actual_value or 'missing'}")
        if state != "OK":
            configuration_errors.append((name, expected_value, actual_value))
    revision_error = revision != expected
    if revision_error:
        print(
            "ERROR: repository revision differs from the course-pinned commit.",
            file=sys.stderr,
        )
    if missing:
        print("ERROR: build the repository before running the adapter.", file=sys.stderr)
    if configuration_errors:
        for name, expected_value, actual_value in configuration_errors:
            print(
                f"ERROR: {name}={actual_value or 'missing'}, expected {expected_value}.",
                file=sys.stderr,
            )
        print("Re-run the course preparation script.", file=sys.stderr)
    if revision_error or missing or configuration_errors:
        return 2
    print("DOCTOR PASS")
    return 0


def command_string(command: list[str]) -> str:
    return shlex.join(command)


def run_logged(
    command: list[str],
    output_dir: Path,
    metadata: dict[str, Any],
    dry_run: bool,
    extra_files: dict[str, str] | None = None,
) -> str:
    print(command_string(command))
    if dry_run:
        return ""
    output_dir.mkdir(parents=True, exist_ok=False)
    for relative_name, contents in (extra_files or {}).items():
        target = output_dir / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")
    record = {**metadata, "command": command}
    (output_dir / "command.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    captured: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="")
        captured.append(line)
    exit_code = process.wait()
    elapsed_seconds = time.perf_counter() - started
    peak_rss_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    text = "".join(captured)
    (output_dir / "run.log").write_text(text, encoding="utf-8")
    record["exit_code"] = exit_code
    record["elapsed_seconds"] = elapsed_seconds
    record["peak_rss_kb"] = peak_rss_kb
    (output_dir / "command.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if exit_code != 0:
        raise subprocess.CalledProcessError(exit_code, command)
    return text


def index_size_bytes(prefix: Path) -> int:
    return sum(
        path.stat().st_size
        for path in prefix.parent.iterdir()
        if path.is_file() and path.name.startswith(prefix.name)
    )


def enrich_rows(
    rows: list[dict[str, Any]],
    repo: Path,
    prefix: Path,
    output_dir: Path,
) -> None:
    record = json.loads((output_dir / "command.json").read_text(encoding="utf-8"))
    shared = {
        "system_commit": git_revision(repo) or "",
        "index_bytes": index_size_bytes(prefix),
        "elapsed_seconds": record.get("elapsed_seconds", ""),
        "peak_rss_kb": record.get("peak_rss_kb", ""),
    }
    for row in rows:
        row.update(shared)


def bucket_summary(workload_dir: Path) -> dict[str, str | int]:
    values: list[float] = []
    query_count = 0
    with (workload_dir / "labels.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            values.append(float(row["selectivity"]))
            query_count += int(row["query_count"])
    values.sort()
    middle = len(values) // 2
    median = (
        values[middle]
        if len(values) % 2
        else (values[middle - 1] + values[middle]) / 2
    )
    return {
        "queries": query_count,
        "selectivity_min": f"{values[0]:.9f}",
        "selectivity_median": f"{median:.9f}",
        "selectivity_max": f"{values[-1]:.9f}",
    }


def write_results(
    output_dir: Path,
    system: str,
    tier: str,
    bucket: str,
    workload_dir: Path,
    rows: list[dict[str, Any]],
    raw_log: Path,
) -> None:
    summary = bucket_summary(workload_dir)
    normalized = []
    for row in rows:
        normalized.append(
            {
                column: (
                    row.get(column, "")
                    if column not in summary
                    else summary[column]
                )
                for column in RESULT_COLUMNS
            }
        )
        normalized[-1].update(
            {
                "system": system,
                "tier": tier,
                "bucket": bucket,
                "raw_log": str(raw_log),
            }
        )
    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(normalized)


def numeric_rows(text: str, minimum_columns: int) -> list[list[float]]:
    parsed: list[list[float]] = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < minimum_columns:
            continue
        try:
            values = [float(token) for token in tokens]
        except ValueError:
            continue
        parsed.append(values)
    return parsed


def main_guard(callback: Callable[[], int | None]) -> None:
    try:
        status = callback()
    except (FileNotFoundError, FileExistsError, ValueError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)
    except subprocess.CalledProcessError as error:
        print(f"ERROR: command exited with status {error.returncode}", file=sys.stderr)
        raise SystemExit(error.returncode)
    raise SystemExit(status or 0)
