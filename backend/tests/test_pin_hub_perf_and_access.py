"""PIN Hub perf helpers + employee Mobile PIN Access as sole employee gate."""

from unittest.mock import MagicMock, patch

from backend.daily_revenue_cost_routes import _drc_access_error
from backend.employee_mobile_pin_access import (
    ensure_org_mobile_pin_access_backfill,
    ACCESS_TABLE,
    BACKFILL_MARKER_TABLE,
)
from backend.employee_pin_hub import resolve_hub_features


def test_ensure_org_skips_create_when_tables_exist():
    cursor = MagicMock()
    with patch(
        "backend.employee_mobile_pin_access.table_exists",
        side_effect=lambda _c, name: name in {ACCESS_TABLE, BACKFILL_MARKER_TABLE},
    ), patch(
        "backend.employee_mobile_pin_access.ensure_employee_mobile_pin_access_tables"
    ) as ensure:
        ensure_org_mobile_pin_access_backfill(cursor, 3)
        ensure.assert_not_called()


def test_get_access_row_does_not_create_tables():
    from backend.employee_mobile_pin_access import get_access_row

    cursor = MagicMock()
    cursor.fetchone.return_value = None
    with patch(
        "backend.employee_mobile_pin_access.table_exists", return_value=True
    ), patch(
        "backend.employee_mobile_pin_access.ensure_employee_mobile_pin_access_tables"
    ) as ensure:
        get_access_row(cursor, 3, 23)
        ensure.assert_not_called()
        cursor.execute.assert_called_once()


def test_ensure_org_creates_when_missing():
    cursor = MagicMock()
    with patch(
        "backend.employee_mobile_pin_access.table_exists", return_value=False
    ), patch(
        "backend.employee_mobile_pin_access.ensure_employee_mobile_pin_access_tables"
    ) as ensure:
        ensure_org_mobile_pin_access_backfill(cursor, 3)
        ensure.assert_called_once()


def test_hub_features_do_not_require_washpro_permission_keys():
    matched = {"id": 23, "_roles": ["SYSTEM"]}
    emp = {
        "clock": False,
        "switch_role": True,
        "checklist": True,
        "inventory": True,
        "revenue_cost": True,
    }
    with patch(
        "backend.employee_pin_hub.load_pin_menu_settings",
        return_value={
            "enabled": True,
            "allow_clock_from_hub": True,
            "features": {
                "switch_role": True,
                "checklist": True,
                "inventory": True,
                "revenue_cost": True,
            },
        },
    ), patch(
        "backend.employee_pin_hub.is_category_role_tracking_enabled", return_value=True
    ), patch(
        "backend.employee_pin_hub._tenant_modules_enabled",
        return_value={"inventory": True, "finance": True},
    ), patch(
        "backend.employee_pin_hub._permission_keys"
    ) as keys_fn:
        feats = resolve_hub_features(
            MagicMock(),
            org_id=3,
            matched=matched,
            employee_module_access=emp,
            effective_keys_fn=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not load keys")),
        )
        keys_fn.assert_not_called()
        assert feats["inventory"]["allowed"] is True
        assert feats["revenue_cost"]["allowed"] is True
        assert feats["checklist"]["allowed"] is True


def test_drc_access_allows_admin_without_mpa():
    me = {"user_id": 1, "roles": ["ADMIN"], "organization_id": 3}
    err, code = _drc_access_error(MagicMock(), me, lambda m: int(m["organization_id"]))
    assert err is None and code is None


def test_drc_access_allows_employee_with_mpa_revenue_cost():
    me = {"user_id": 23, "roles": ["SYSTEM"], "organization_id": 3}
    with patch(
        "backend.employee_mobile_pin_access.assert_employee_allows_module"
    ) as assert_mod:
        err, code = _drc_access_error(MagicMock(), me, lambda m: int(m["organization_id"]))
        assert err is None and code is None
        assert_mod.assert_called_once()
        assert assert_mod.call_args.args[3] == "revenue_cost"


def test_drc_access_denies_employee_without_mpa():
    from backend.app import app
    from backend.employee_mobile_pin_access import MobilePinAccessDeniedError

    me = {"user_id": 23, "roles": ["SYSTEM"], "organization_id": 3}
    with app.app_context(), patch(
        "backend.employee_mobile_pin_access.assert_employee_allows_module",
        side_effect=MobilePinAccessDeniedError(),
    ):
        err, code = _drc_access_error(MagicMock(), me, lambda m: int(m["organization_id"]))
        assert code == 403
        assert err is not None
