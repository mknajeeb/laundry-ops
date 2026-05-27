"""Rules impact summary helpers."""

from backend.rinse_folding_exception_rules import MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST
from backend.rinse_folding_rules_impact import (
    _impact_from_rows,
    rules_status_summary,
)


class TestRulesImpact:
    def test_rules_status_summary_warning_default(self):
        s = rules_status_summary({"multiple_folding_scans_behavior": MULTIPLE_FOLDING_BEHAVIOR_WARNING_EARLIEST})
        assert "Warning" in s["multiple_folding_scans"]
        assert s["min_duration_minutes"] == 10

    def test_impact_counts_warning_in_scoring(self):
        impact = _impact_from_rows(
            [
                {
                    "exception_code": "MULTIPLE_FOLDING_SCANS",
                    "status": "CALCULATED",
                    "scoring_status": "CALCULATED",
                    "included_in_scoring": 1,
                },
                {
                    "exception_code": "FOLDING_DURATION_TOO_SHORT",
                    "status": "EXCEPTION",
                    "scoring_status": "EXCEPTION",
                    "included_in_scoring": 0,
                },
            ]
        )
        assert impact["total_bags"] == 2
        assert impact["included_in_scoring"] == 1
        assert impact["warning_in_scoring"] == 1
        assert impact["multiple_folding_scans_warning_in_scoring"] == 1
        assert impact["too_short_duration"] == 1

    def test_impact_counts_secondary_multiple_folding_warning(self):
        import json

        impact = _impact_from_rows(
            [
                {
                    "exception_code": "FOLDING_DURATION_TOO_SHORT",
                    "warning_codes": json.dumps(["MULTIPLE_FOLDING_SCANS"]),
                    "status": "EXCEPTION",
                    "scoring_status": "EXCEPTION",
                    "included_in_scoring": 0,
                },
            ]
        )
        assert impact["too_short_duration"] == 1
        assert impact["multiple_folding_scans_secondary_warning"] == 1
        assert impact["multiple_folding_scans_exception"] == 0
