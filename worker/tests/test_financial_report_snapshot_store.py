import tempfile
import unittest
from pathlib import Path

from services.financial_report_snapshot_store import (
    validate_pdf_response,
    write_snapshot_atomically,
)


class FinancialReportSnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.raw_document = b"%PDF-1.7\nfixed-test-payload"
        import hashlib

        self.candidate = {
            "expected_raw_hash": hashlib.sha256(self.raw_document).hexdigest(),
            "expected_bytes": len(self.raw_document),
        }

    def test_pdf_hash_and_bytes_must_match_existing_evidence(self):
        observed_hash, observed_bytes = validate_pdf_response(
            self.candidate, self.raw_document, "application/pdf"
        )
        self.assertEqual(observed_hash, self.candidate["expected_raw_hash"])
        self.assertEqual(observed_bytes, self.candidate["expected_bytes"])
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            validate_pdf_response(
                self.candidate, self.raw_document + b"changed", "application/pdf"
            )

    def test_pdf_magic_and_content_type_are_required(self):
        with self.assertRaisesRegex(ValueError, "PDF"):
            validate_pdf_response(self.candidate, b"not-pdf", "application/pdf")
        with self.assertRaisesRegex(ValueError, "Content-Type"):
            validate_pdf_response(self.candidate, self.raw_document, "text/html")

    def test_snapshot_write_is_atomic_and_does_not_overwrite_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = write_snapshot_atomically(root, "fixed.pdf", self.raw_document)
            self.assertEqual(target.read_bytes(), self.raw_document)
            reused = write_snapshot_atomically(root, "fixed.pdf", self.raw_document)
            self.assertEqual(reused, target)
            with self.assertRaisesRegex(RuntimeError, "字节不一致"):
                write_snapshot_atomically(root, "fixed.pdf", b"%PDF-changed")

    def test_storage_key_cannot_escape_snapshot_root(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "storage_key"):
                write_snapshot_atomically(
                    Path(directory), "../escaped.pdf", self.raw_document
                )


if __name__ == "__main__":
    unittest.main()
