#!/usr/bin/env python3
"""Tests for strict course environment validation."""

from __future__ import annotations

import argparse
import contextlib
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "adapters"))

from _common import VERSIONS, doctor  # noqa: E402


class DoctorCommitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "system"
        self.repo.mkdir()
        self.binary = self.repo / "search"
        self.binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        self.binary.chmod(0o755)

        tier = self.root / "dataset" / "debug_100000"
        tier.mkdir(parents=True)
        (tier / "base.u8bin").write_bytes(struct.pack("<II", 1, 2) + b"\x00\x00")
        (tier / "base.metadata.spmat").write_bytes(struct.pack("<qqq", 1, 1, 0))
        (tier / "base.labels.txt").write_text("\n", encoding="utf-8")
        self.args = argparse.Namespace(
            repo=self.repo,
            dataset_root=self.root / "dataset",
            tier="debug",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_doctor(self, revision: str | None) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch("_common.git_revision", return_value=revision),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = doctor("pipeann", self.args, [self.binary])
        return status, stdout.getvalue(), stderr.getvalue()

    def test_pinned_commit_passes(self) -> None:
        status, stdout, stderr = self.run_doctor(VERSIONS["pipeann"]["commit"])
        self.assertEqual(status, 0)
        self.assertIn("DOCTOR PASS", stdout)
        self.assertEqual(stderr, "")

    def test_wrong_commit_is_rejected(self) -> None:
        status, stdout, stderr = self.run_doctor("0" * 40)
        self.assertEqual(status, 2)
        self.assertNotIn("DOCTOR PASS", stdout)
        self.assertIn("ERROR: repository revision differs", stderr)

    def test_non_git_directory_is_rejected(self) -> None:
        status, stdout, stderr = self.run_doctor(None)
        self.assertEqual(status, 2)
        self.assertNotIn("DOCTOR PASS", stdout)
        self.assertIn("ERROR: repository revision differs", stderr)


if __name__ == "__main__":
    unittest.main()
