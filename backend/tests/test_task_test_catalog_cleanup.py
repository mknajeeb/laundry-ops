"""The disposable catalog cleanup is an exact allowlist and stops when history exists."""

from backend.task_test_catalog_cleanup import (
    VEEWASH_GROUP_CODES,
    VEEWASH_TASK_CODES,
    WASHPRO_GROUP_CODES,
    apply_test_catalog_cleanup,
    plan_test_catalog_cleanup,
)


class CleanupCursor:
    def __init__(self, history_code=None):
        self.history_code = history_code
        self.statements = []
        self.last = ""

    def execute(self, sql, params=None):
        self.last = " ".join(sql.split())
        self.params = params or ()
        self.statements.append(self.last)

    def fetchone(self):
        if "FROM organizations" in self.last:
            slug = self.params[0]
            return {"id": 3 if slug == "veewash" else 1}
        if "FROM task_activity_groups" in self.last:
            code = self.params[1]
            return {"id": 11, "code": code, "name": code, "active": 0}
        if "FROM weekly_schedule_roles" in self.last and "SELECT" in self.last:
            code = self.params[1]
            return {"id": 40, "active": 0 if code != self.history_code else 0}
        if self.last.startswith("SELECT COUNT"):
            role = self.params[1]
            if role == self.history_code:
                return {"c": 1}
            return {"c": 0}
        return None

    def fetchall(self):
        if "FROM task_activity_group_items" in self.last:
            return []
        return []


def test_allowlist_is_the_reviewed_set_and_spares_live_tasks():
    assert len(VEEWASH_GROUP_CODES) == 5
    assert len(WASHPRO_GROUP_CODES) == 1
    assert len(VEEWASH_TASK_CODES) == 33
    assert "floor_cleaning" not in VEEWASH_TASK_CODES
    assert "lint_cleaning" not in VEEWASH_TASK_CODES
    assert "agroup_dryer_lint" not in VEEWASH_GROUP_CODES


def test_plan_is_ready_when_the_allowlist_has_no_history():
    plan = plan_test_catalog_cleanup(CleanupCursor())
    assert plan["ok"] is True
    assert plan["ready_groups"] == 6
    assert plan["ready_tasks"] == 33
    assert plan["blockers"] == []


def test_plan_stops_when_one_code_has_execution():
    plan = plan_test_catalog_cleanup(CleanupCursor(history_code="custom_e2e_ag_floor_34c74d"))
    assert plan["ok"] is False
    assert any(row.get("code") == "custom_e2e_ag_floor_34c74d" for row in plan["blockers"])


def test_apply_does_not_delete_when_history_blocks_the_plan():
    cursor = CleanupCursor(history_code="agroup_e2e_routine_34c74d")
    report = apply_test_catalog_cleanup(cursor)
    assert report["deleted"] is False
    assert not any(sql.startswith("DELETE") for sql in cursor.statements)
