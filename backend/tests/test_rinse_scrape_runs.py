"""Unit tests for scheduled scrape helpers (no MySQL)."""

import tempfile
import unittest
from pathlib import Path

from backend.rinse_scheduled_scrape import count_csv_data_rows, parse_scheduled_org_ids


class TestCountCsvDataRows(unittest.TestCase):
    def test_counts_data_minus_header(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("a,b\n")
            f.write("1,2\n")
            f.write("3,4\n")
            path = Path(f.name)
        try:
            self.assertEqual(count_csv_data_rows(path), 2)
        finally:
            path.unlink(missing_ok=True)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            path = Path(f.name)
        try:
            self.assertEqual(count_csv_data_rows(path), 0)
        finally:
            path.unlink(missing_ok=True)

    def test_header_only(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("h1,h2\n")
            path = Path(f.name)
        try:
            self.assertEqual(count_csv_data_rows(path), 0)
        finally:
            path.unlink(missing_ok=True)


class TestParseScheduledOrgIds(unittest.TestCase):
    def test_comma_separated_deduped(self):
        import os

        old = os.environ.get("RINSE_SCHEDULED_ORG_IDS")
        try:
            os.environ["RINSE_SCHEDULED_ORG_IDS"] = "3,1,3, 5"
            self.assertEqual(parse_scheduled_org_ids(), [3, 1, 5])
        finally:
            if old is None:
                os.environ.pop("RINSE_SCHEDULED_ORG_IDS", None)
            else:
                os.environ["RINSE_SCHEDULED_ORG_IDS"] = old


if __name__ == "__main__":
    unittest.main()
