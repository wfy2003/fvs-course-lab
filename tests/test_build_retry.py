#!/usr/bin/env python3
"""Tests for recoverable index build attempts."""

from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "adapters"))

from _common import (  # noqa: E402
    begin_index_build,
    finish_index_build,
    preserve_failed_index_build,
)


class BuildRetryTest(unittest.TestCase):
    def test_failed_attempt_can_be_retried_and_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tier = root / "dataset" / "debug_100000"
            tier.mkdir(parents=True)
            args = argparse.Namespace(
                run_root=root / "runs",
                reuse_existing=False,
                dry_run=False,
            )

            legacy_directory = args.run_root / "indices" / "pipeann" / tier.name
            legacy_directory.mkdir(parents=True)
            (legacy_directory / "partial-file").write_text("partial", encoding="utf-8")

            first = begin_index_build(args, "pipeann", tier)
            self.assertIsNotNone(first)
            assert first is not None
            self.assertFalse(legacy_directory.exists())
            self.assertTrue(first.staging_prefix.parent.is_dir())
            self.assertEqual(len(list(legacy_directory.parent.glob(".debug_100000.incomplete-*"))), 1)

            preserve_failed_index_build(first)
            self.assertFalse(first.staging_prefix.parent.exists())
            self.assertEqual(len(list(legacy_directory.parent.glob(".debug_100000.failed-*"))), 1)

            second = begin_index_build(args, "pipeann", tier)
            self.assertIsNotNone(second)
            assert second is not None
            self.assertNotEqual(first.attempt_id, second.attempt_id)
            Path(str(second.staging_prefix) + "_disk.index").write_bytes(b"index")
            finish_index_build(second)

            signature = Path(str(second.final_prefix) + "_disk.index")
            self.assertTrue(signature.is_file())
            args.reuse_existing = True
            self.assertIsNone(begin_index_build(args, "pipeann", tier))

    def test_dry_run_does_not_touch_index_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tier = root / "dataset" / "debug_100000"
            tier.mkdir(parents=True)
            args = argparse.Namespace(
                run_root=root / "runs",
                reuse_existing=False,
                dry_run=True,
            )

            attempt = begin_index_build(args, "gateann", tier)
            self.assertIsNotNone(attempt)
            self.assertFalse((args.run_root / "indices").exists())


if __name__ == "__main__":
    unittest.main()
