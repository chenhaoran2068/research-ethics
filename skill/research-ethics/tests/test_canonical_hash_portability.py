"""Regression test: canonical ledger hashes must survive CRLF/LF conversion."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_dfs_ledger import sha256_file  # noqa: E402


class CanonicalHashPortabilityTests(unittest.TestCase):
    def test_crlf_and_lf_yaml_have_the_same_content_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lf = root / "canonical-lf.yaml"
            crlf = root / "canonical-crlf.yaml"
            lf.write_bytes(b"schema_version: '0.1'\nworkflow: test\n")
            crlf.write_bytes(b"schema_version: '0.1'\r\nworkflow: test\r\n")
            self.assertEqual(sha256_file(lf), sha256_file(crlf))


if __name__ == "__main__":
    unittest.main()
