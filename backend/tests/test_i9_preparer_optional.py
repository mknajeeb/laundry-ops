"""I-9 preparer/translator rows are optional; empty rows are stripped on merge."""

import unittest

from backend.hr_compliance import _deep_merge_work_json, _sanitize_i9_block


class TestI9PreparerOptional(unittest.TestCase):
    def test_sanitize_drops_blank_preparer_rows(self):
        i9 = {
            "citizenship": "1",
            "preparers": [
                {"last_name": "", "first_name": "", "address": "", "city": "", "state": "", "zip": ""},
                {
                    "last_name": "Smith",
                    "first_name": "Pat",
                    "address": "1 Main",
                    "city": "Bronx",
                    "state": "NY",
                    "zip": "10455",
                },
            ],
        }
        out = _sanitize_i9_block(i9)
        self.assertEqual(len(out["preparers"]), 1)
        self.assertEqual(out["preparers"][0]["last_name"], "Smith")

    def test_merge_work_json_strips_empty_preparers(self):
        merged = _deep_merge_work_json(
            {},
            {
                "i9": {
                    "preparers": [{"last_name": " ", "first_name": ""}],
                }
            },
        )
        self.assertEqual(merged["i9"]["preparers"], [])


if __name__ == "__main__":
    unittest.main()
