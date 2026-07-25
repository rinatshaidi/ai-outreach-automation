import csv
import unittest
from pathlib import Path

from personalize import audit_email_domain, enrich, normalized_host


class DomainAuditTests(unittest.TestCase):
    def test_normalized_host_removes_protocol_path_and_www(self):
        self.assertEqual(normalized_host("https://www.Example.ru/products"), "example.ru")

    def test_matching_domain_is_accepted(self):
        self.assertEqual(audit_email_domain("sales@example.ru", "https://example.ru").status, "matched")

    def test_mismatch_is_flagged(self):
        self.assertEqual(
            audit_email_domain("sales@other.example", "https://company.example").status,
            "domain_mismatch",
        )


class PipelineTests(unittest.TestCase):
    def test_offline_mode_fails_closed_for_mismatched_domains(self):
        input_path = Path(__file__).parent.parent / "examples" / "leads.sample.csv"
        output_path = Path(__file__).parent / "_pipeline_output.csv"

        enrich(input_path, output_path, use_llm=False, timeout=1)

        with output_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["audit_status"], "matched")
        self.assertEqual(rows[1]["audit_status"], "domain_mismatch")
        self.assertIn("skipped", rows[1]["error"])


if __name__ == "__main__":
    unittest.main()
