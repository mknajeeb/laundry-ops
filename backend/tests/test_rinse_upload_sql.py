"""Upload batch row INSERT SQL builder and NaN-safe bind args."""

from __future__ import annotations

import unittest

import pandas as pd

from backend.rinse_upload_sql import (
    bool_sql_flag,
    build_upload_batch_row_insert_sql,
    null_if_na,
    special_instruction_insert_args,
)


class TestNullIfNa(unittest.TestCase):
    def test_pandas_na_becomes_none(self):
        self.assertIsNone(null_if_na(pd.NA))

    def test_float_nan_becomes_none(self):
        self.assertIsNone(null_if_na(float("nan")))

    def test_bool_sql_flag_handles_pandas_na(self):
        self.assertEqual(bool_sql_flag(pd.NA), 0)
        self.assertEqual(bool_sql_flag(True), 1)


class TestUploadBatchRowInsertSql(unittest.TestCase):
    def test_sql_never_contains_nan_column_name(self):
        sql = build_upload_batch_row_insert_sql(
            include_ticket_id=True,
            include_special_instructions=True,
            timestamp_cols_sql=", created_at, updated_at",
            timestamp_vals_sql=", NOW(), NOW()",
        )
        self.assertIn("special_instructions_raw", sql)
        self.assertNotIn(" nan", sql.lower())
        self.assertNotIn("(nan", sql.lower())

    def test_special_instruction_args_sanitize_na(self):
        row = pd.Series(
            {
                "special_instructions_raw": pd.NA,
                "supply_interpretation": float("nan"),
                "special_instruction_review": pd.NA,
            }
        )
        args = special_instruction_insert_args(row, include=True)
        self.assertEqual(args, [None, None, 0])

    def test_special_instruction_args_empty_strings(self):
        row = pd.Series(
            {
                "special_instructions_raw": "",
                "supply_interpretation": "   ",
                "special_instruction_review": False,
            }
        )
        args = special_instruction_insert_args(row, include=True)
        self.assertEqual(args, ["", "   ", 0])

    def test_special_instruction_args_missing_fields(self):
        row = pd.Series({"Date_Clean": "2026-06-09"})
        args = special_instruction_insert_args(row, include=True)
        self.assertEqual(args, [None, None, 0])

    def test_null_if_na_none_and_blank(self):
        self.assertIsNone(null_if_na(None))
        self.assertEqual(null_if_na(""), "")


if __name__ == "__main__":
    unittest.main()
