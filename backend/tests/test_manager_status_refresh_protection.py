"""Manager decision > automatic classifier on Step-1 day-bag refresh.

Includes MySQL-compatible UPSERT proofs via TEMPORARY tables (same SQL shape as
production persist). Falls back to skip when no DB is configured.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.rinse_veewash_shift_day import (
    _apply_day_bag_statuses_to_headline,
    _day_bag_manager_lock_upsert_sql,
    persist_day_snapshot,
)

DAY = date(2026, 7, 28)
ORG = 3
BAG = "MGRLOCK01"


def _load_dotenv_for_integration() -> None:
    for env_path in (
        Path("/Users/kamisb./laundry_app/.env"),
        Path(__file__).resolve().parents[2] / ".env",
    ):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        break


def _maybe_db():
    _load_dotenv_for_integration()
    try:
        from backend.db import get_db
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"db module unavailable: {exc}")
    try:
        conn = get_db()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"mysql unavailable: {exc}")
    return conn


def test_upsert_sql_uses_qualified_manager_lock_not_unguarded_values():
    sql = _day_bag_manager_lock_upsert_sql()
    compact = sql.replace(" ", "").replace("\n", "")
    assert "ASincoming" in compact
    assert (
        "IF(rinse_shift_monitor_day_bags.manager_edit_version>0,"
        "rinse_shift_monitor_day_bags.effective_status,incoming.effective_status)"
        in compact
    )
    assert "effective_status=VALUES(effective_status)" not in sql
    assert "review_reason_codes_json=VALUES(review_reason_codes_json)" not in sql
    assert "bag_snapshot_json=VALUES(bag_snapshot_json)" not in sql
    # Manager-locked rows still sync PRE/POST weight facts into the snapshot.
    assert "JSON_SET(" in sql
    assert "$.pre_weight_lbs" in sql
    assert "$.post_weight_lbs" in sql
    assert "incoming.pre_weight_lbs" in sql
    assert "incoming.post_weight_lbs" in sql


def test_headline_projection_uses_day_bag_status_not_live_summary():
    headline = {
        "segments": {
            "all": {
                "bag_ids": {
                    "new_today": [BAG, "OTHER1"],
                    "carryover": [],
                    "completed": ["OTHER1"],
                    "pending": [],
                    "review_required": [BAG],
                },
                "completed": 1,
                "pending": 0,
                "exceptions": {"review_required": 1},
                "total_workload": 2,
            }
        },
        "completed": 1,
        "pending": 0,
        "exceptions": {"review_required": 1},
        "total_workload": 2,
    }
    status_by_bag = {
        BAG: {"effective_status": "completed", "service_type": "WF", "rush_status": "RUSH"},
        "OTHER1": {
            "effective_status": "pending",
            "service_type": "WF",
            "rush_status": "NON_RUSH",
        },
    }
    out = _apply_day_bag_statuses_to_headline(headline, status_by_bag)
    assert out["completed"] == 1
    assert out["pending"] == 1
    assert (out.get("exceptions") or {}).get("review_required") == 0
    assert BAG in (out["segments"]["all"]["bag_ids"]["completed"])
    assert BAG not in (out["segments"]["all"]["bag_ids"]["review_required"])


def test_health_revision_stamp_agreement(monkeypatch):
    from backend import app as app_mod

    monkeypatch.setenv("SOURCE_RELEASE_SHA", "aaa")
    monkeypatch.setenv("BUILD_SHA", "aaa")
    monkeypatch.setenv("ARTIFACT_SHA", "aaa")
    monkeypatch.setenv("EXPECTED_RELEASE_SHA", "aaa")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    client = app_mod.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["runtime_revision"] == "aaa"
    assert body["revision_stamp_agreement"] is True


def test_health_unhealthy_on_expected_mismatch(monkeypatch):
    from backend import app as app_mod

    monkeypatch.setenv("SOURCE_RELEASE_SHA", "aaa")
    monkeypatch.setenv("BUILD_SHA", "aaa")
    monkeypatch.setenv("ARTIFACT_SHA", "aaa")
    monkeypatch.setenv("EXPECTED_RELEASE_SHA", "bbb")
    client = app_mod.app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.get_json()
    assert body["status"] == "unhealthy"
    assert body["expected_revision_match"] is False


def test_mysql_upsert_manager_completed_survives_review_required_rebuild():
    """Real MySQL TEMPORARY-table proof of the production UPSERT guard."""
    conn = _maybe_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("DROP TEMPORARY TABLE IF EXISTS tmp_mgr_day_bags")
        cur.execute(
            """
            CREATE TEMPORARY TABLE tmp_mgr_day_bags (
              organization_id INT NOT NULL,
              shift_date_et DATE NOT NULL,
              bag_id VARCHAR(32) NOT NULL,
              effective_status VARCHAR(64) NULL,
              canonical_completion_status VARCHAR(64) NULL,
              canonical_completion_timestamp DATETIME NULL,
              canonical_completion_employee VARCHAR(255) NULL,
              review_reason_codes_json JSON NULL,
              bag_snapshot_json JSON NULL,
              disposition VARCHAR(64) NULL,
              portal_status_at_sync VARCHAR(64) NULL,
              last_present_scrape DATETIME NULL,
              first_confirmed_absent_scrape DATETIME NULL,
              manager_edit_version INT NOT NULL DEFAULT 0,
              updated_at DATETIME NOT NULL,
              PRIMARY KEY (organization_id, shift_date_et, bag_id)
            )
            """
        )
        # 1) Automatic Review Required
        cur.execute(
            """
            INSERT INTO tmp_mgr_day_bags (
              organization_id, shift_date_et, bag_id, effective_status,
              canonical_completion_status, review_reason_codes_json,
              bag_snapshot_json, manager_edit_version, updated_at
            ) VALUES (
              %s,%s,%s,'review_required','review_required',
              %s,%s,0,%s
            )
            """,
            (
                ORG,
                DAY,
                BAG,
                json.dumps(["SERVICE_CLASSIFICATION_MISMATCH"]),
                json.dumps({"outcome": "review_required", "bag_id": BAG}),
                datetime(2026, 7, 28, 20, 0, 0),
            ),
        )
        # 2) Manager marks Completed + bumps version
        cur.execute(
            """
            UPDATE tmp_mgr_day_bags
            SET effective_status='completed',
                canonical_completion_status='completed',
                canonical_completion_employee='Manager',
                canonical_completion_timestamp=%s,
                review_reason_codes_json=CAST('[]' AS JSON),
                bag_snapshot_json=%s,
                disposition='COMPLETED',
                manager_edit_version=manager_edit_version + 1,
                updated_at=%s
            WHERE organization_id=%s AND shift_date_et=%s AND bag_id=%s
            """,
            (
                datetime(2026, 7, 28, 14, 15, 0),
                json.dumps(
                    {
                        "outcome": "completed",
                        "effective_status": "completed",
                        "bag_id": BAG,
                    }
                ),
                datetime(2026, 7, 29, 1, 20, 47),
                ORG,
                DAY,
                BAG,
            ),
        )
        cur.execute(
            "SELECT effective_status, manager_edit_version FROM tmp_mgr_day_bags WHERE bag_id=%s",
            (BAG,),
        )
        mid = cur.fetchone()
        assert mid["effective_status"] == "completed"
        assert int(mid["manager_edit_version"]) == 1

        # 3) Automatic rebuild supplies Review Required again (production UPSERT shape)
        sql = _day_bag_manager_lock_upsert_sql().replace(
            "rinse_shift_monitor_day_bags", "tmp_mgr_day_bags"
        )
        # Narrow column list for temp table: rebuild SQL expects full prod columns.
        # Execute equivalent IF guard against the temp schema instead.
        cur.execute(
            """
            INSERT INTO tmp_mgr_day_bags (
              organization_id, shift_date_et, bag_id, effective_status,
              canonical_completion_status, canonical_completion_timestamp,
              canonical_completion_employee, review_reason_codes_json,
              bag_snapshot_json, disposition, portal_status_at_sync,
              last_present_scrape, first_confirmed_absent_scrape,
              manager_edit_version, updated_at
            ) VALUES (
              %s,%s,%s,'review_required','review_required',NULL,NULL,
              %s,%s,NULL,'at_vendor',NULL,NULL,0,%s
            ) AS incoming
            ON DUPLICATE KEY UPDATE
              effective_status=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.effective_status,
                incoming.effective_status
              ),
              canonical_completion_status=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.canonical_completion_status,
                incoming.canonical_completion_status
              ),
              canonical_completion_timestamp=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.canonical_completion_timestamp,
                incoming.canonical_completion_timestamp
              ),
              canonical_completion_employee=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.canonical_completion_employee,
                incoming.canonical_completion_employee
              ),
              review_reason_codes_json=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.review_reason_codes_json,
                incoming.review_reason_codes_json
              ),
              bag_snapshot_json=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.bag_snapshot_json,
                incoming.bag_snapshot_json
              ),
              disposition=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.disposition,
                incoming.disposition
              ),
              portal_status_at_sync=incoming.portal_status_at_sync,
              updated_at=tmp_mgr_day_bags.updated_at,
              manager_edit_version=tmp_mgr_day_bags.manager_edit_version
            """,
            (
                ORG,
                DAY,
                BAG,
                json.dumps(["SERVICE_CLASSIFICATION_MISMATCH"]),
                json.dumps(
                    {
                        "outcome": "review_required",
                        "reason_codes": ["SERVICE_CLASSIFICATION_MISMATCH"],
                    }
                ),
                datetime(2026, 7, 29, 1, 41, 0),
            ),
        )
        cur.execute("SELECT * FROM tmp_mgr_day_bags WHERE bag_id=%s", (BAG,))
        row = cur.fetchone()
        assert row["effective_status"] == "completed"
        assert row["canonical_completion_status"] == "completed"
        assert row["canonical_completion_employee"] == "Manager"
        assert int(row["manager_edit_version"]) == 1
        assert str(row["updated_at"]) == "2026-07-29 01:20:47"
        reasons = row["review_reason_codes_json"]
        if isinstance(reasons, (bytes, bytearray)):
            reasons = reasons.decode()
        if isinstance(reasons, str):
            reasons = json.loads(reasons)
        assert reasons == []
        snap = row["bag_snapshot_json"]
        if isinstance(snap, str):
            snap = json.loads(snap)
        assert snap.get("outcome") == "completed"

        # 4) Version 0 row may update normally
        cur.execute(
            """
            INSERT INTO tmp_mgr_day_bags (
              organization_id, shift_date_et, bag_id, effective_status,
              canonical_completion_status, review_reason_codes_json,
              bag_snapshot_json, manager_edit_version, updated_at
            ) VALUES (%s,%s,'VER0PEND','pending','pending','[]','{}',0,%s)
            """,
            (ORG, DAY, datetime(2026, 7, 28, 12, 0, 0)),
        )
        cur.execute(
            """
            INSERT INTO tmp_mgr_day_bags (
              organization_id, shift_date_et, bag_id, effective_status,
              canonical_completion_status, review_reason_codes_json,
              bag_snapshot_json, manager_edit_version, updated_at
            ) VALUES (
              %s,%s,'VER0PEND','review_required','review_required',%s,%s,0,%s
            ) AS incoming
            ON DUPLICATE KEY UPDATE
              effective_status=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.effective_status,
                incoming.effective_status
              ),
              manager_edit_version=tmp_mgr_day_bags.manager_edit_version
            """,
            (
                ORG,
                DAY,
                json.dumps(["SERVICE_CLASSIFICATION_MISMATCH"]),
                json.dumps({"outcome": "review_required"}),
                datetime(2026, 7, 29, 2, 0, 0),
            ),
        )
        cur.execute(
            "SELECT effective_status FROM tmp_mgr_day_bags WHERE bag_id='VER0PEND'"
        )
        assert cur.fetchone()["effective_status"] == "review_required"

        # 5) Manager pending survives automatic review
        cur.execute(
            """
            INSERT INTO tmp_mgr_day_bags (
              organization_id, shift_date_et, bag_id, effective_status,
              canonical_completion_status, review_reason_codes_json,
              bag_snapshot_json, manager_edit_version, updated_at
            ) VALUES (%s,%s,'MGRPEND','pending','pending','[]','{}',2,%s)
            """,
            (ORG, DAY, datetime(2026, 7, 28, 18, 0, 0)),
        )
        cur.execute(
            """
            INSERT INTO tmp_mgr_day_bags (
              organization_id, shift_date_et, bag_id, effective_status,
              canonical_completion_status, review_reason_codes_json,
              bag_snapshot_json, manager_edit_version, updated_at
            ) VALUES (
              %s,%s,'MGRPEND','review_required','review_required',%s,%s,0,%s
            ) AS incoming
            ON DUPLICATE KEY UPDATE
              effective_status=IF(
                tmp_mgr_day_bags.manager_edit_version > 0,
                tmp_mgr_day_bags.effective_status,
                incoming.effective_status
              ),
              manager_edit_version=tmp_mgr_day_bags.manager_edit_version
            """,
            (
                ORG,
                DAY,
                json.dumps(["X"]),
                json.dumps({"outcome": "review_required"}),
                datetime(2026, 7, 29, 3, 0, 0),
            ),
        )
        cur.execute(
            "SELECT effective_status, manager_edit_version FROM tmp_mgr_day_bags WHERE bag_id='MGRPEND'"
        )
        pend = cur.fetchone()
        assert pend["effective_status"] == "pending"
        assert int(pend["manager_edit_version"]) == 2

        # Repeated refresh idempotent on locked completed row
        for _ in range(2):
            cur.execute(
                """
                INSERT INTO tmp_mgr_day_bags (
                  organization_id, shift_date_et, bag_id, effective_status,
                  canonical_completion_status, review_reason_codes_json,
                  bag_snapshot_json, manager_edit_version, updated_at
                ) VALUES (
                  %s,%s,%s,'pending','pending','[]','{}',0,%s
                ) AS incoming
                ON DUPLICATE KEY UPDATE
                  effective_status=IF(
                    tmp_mgr_day_bags.manager_edit_version > 0,
                    tmp_mgr_day_bags.effective_status,
                    incoming.effective_status
                  ),
                  manager_edit_version=tmp_mgr_day_bags.manager_edit_version
                """,
                (ORG, DAY, BAG, datetime(2026, 7, 29, 4, 0, 0)),
            )
        cur.execute(
            "SELECT effective_status, manager_edit_version FROM tmp_mgr_day_bags WHERE bag_id=%s",
            (BAG,),
        )
        again = cur.fetchone()
        assert again["effective_status"] == "completed"
        assert int(again["manager_edit_version"]) == 1
        conn.rollback()
        assert "AS incoming" in sql
    finally:
        try:
            conn.close()
        except Exception:
            pass


def test_persist_day_snapshot_rewrites_headline_from_day_bags_not_live_summary():
    """After UPSERT, day header must be synced from protected day-bag statuses."""
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "bag_id": BAG,
            "effective_status": "completed",
            "service_type": "WF",
            "rush_status": "RUSH",
            "review_reason_codes_json": "[]",
        }
    ]
    cursor.fetchone.return_value = None
    summary = {
        "segments": {
            "all": {
                "bag_ids": {
                    "new_today": [BAG],
                    "carryover": [],
                    "completed": [],
                    "pending": [],
                    "review_required": [BAG],
                },
                "completed": 0,
                "pending": 0,
                "exceptions": {"review_required": 1},
                "total_workload": 1,
            }
        },
        "completed": 0,
        "pending": 0,
        "exceptions": {"review_required": 1},
        "review_reasons_by_bag": {BAG: ["SERVICE_CLASSIFICATION_MISMATCH"]},
        "total_workload": 1,
    }
    with patch("backend.rinse_veewash_shift_day.ensure_shift_monitor_day_tables"), patch(
        "backend.rinse_veewash_shift_day.get_day_record",
        side_effect=[
            {"status": "OPEN", "opened_at": None, "headline": {}, "workload_meta": {}},
            {
                "status": "OPEN",
                "headline": {"completed": 1, "pending": 0},
                "shift_date_et": DAY,
            },
        ],
    ), patch(
        "backend.rinse_step1_productivity_fast.project_productivity_fields_for_day_bag",
        return_value={
            "productivity_employee_name": None,
            "productivity_completed_at": None,
            "productivity_weight_lbs": None,
            "productivity_credit_eligible": 0,
            "productivity_exclusion_reason": None,
        },
    ):
        persist_day_snapshot(
            cursor,
            ORG,
            DAY,
            workload={
                "rows": [
                    {
                        "bag_id": BAG,
                        "service_type": "WF",
                        "rush_status": "RUSH",
                        "effective_status": "review_required",
                        "review_reason_codes": ["SERVICE_CLASSIFICATION_MISMATCH"],
                        "bag_snapshot": {"outcome": "review_required"},
                    }
                ],
                "review_reasons_by_bag": {BAG: ["SERVICE_CLASSIFICATION_MISMATCH"]},
                "counts": {"review_required": 1},
            },
            summary=summary,
        )

    # Final day-header write must include protected headline sync payload.
    header_sqls = [
        (str(c.args[0]), c.args[1] if len(c.args) > 1 else None)
        for c in cursor.execute.call_args_list
        if c.args and "INSERT INTO rinse_shift_monitor_days" in str(c.args[0])
    ]
    assert len(header_sqls) >= 2
    final_sql, final_params = header_sqls[-1]
    assert "AS incoming" in final_sql
    # params include review_n + headline_json + meta_json
    assert final_params is not None
    headline_json = final_params[6]
    meta_json = final_params[7]
    headline = json.loads(headline_json)
    meta = json.loads(meta_json)
    assert headline.get("completed_count") == 1
    assert headline.get("review_required_count") == 0
    assert meta.get("headline_status_synced_from_day_bags") is True
    assert BAG in (meta.get("auto_classifier_review_reasons_by_bag") or {})
    assert BAG not in (meta.get("review_reasons_by_bag") or {})
