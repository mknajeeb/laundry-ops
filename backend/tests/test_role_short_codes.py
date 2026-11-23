"""Three-character role codes stay unique without rewriting role ids."""

from pathlib import Path

from backend.weekly_schedule_roles import (
    assign_short_codes,
    default_role_catalog,
    list_role_catalog,
    propose_short_code,
    update_role,
)


class _CatalogCursor:
    """Records SQL. A missing short_code column stays missing."""

    def __init__(self, *, has_short_code: bool):
        self.has_short_code = has_short_code
        self.statements: list[str] = []
        self.saved: list[tuple] = []
        self._kind = ""

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.statements.append(text)
        self._kind = text.lower()
        if self._kind.startswith("insert into weekly_schedule_roles"):
            self.saved.append(tuple(params or ()))

    def fetchone(self):
        if self._kind.startswith("show columns") and self.has_short_code:
            return {"Field": "short_code"}
        return None

    def fetchall(self):
        return []


def test_builtin_roles_receive_the_agreed_codes():
    marks = {role["code"]: role["short_code"] for role in default_role_catalog()}
    assert marks["weigher"] == "WGH"
    assert marks["sort"] == "SRT"
    assert marks["wash"] == "WSH"
    assert marks["fold"] == "FLD"
    assert marks["dry"] == "DRY"
    assert marks["hd_folder"] == "HDF"
    assert marks["hd_operator"] == "HDO"
    assert len(set(marks.values())) == len(marks)


def test_a_stored_code_wins_and_a_collision_is_given_another_code():
    rows = assign_short_codes(
        [
            {"code": "weigher", "name": "Weigher", "short_code": "SRT"},
            {"code": "sort", "name": "Sort", "short_code": None},
            {"code": "custom_veewash_folder", "name": "VeeWash Folder", "short_code": None},
        ]
    )
    marks = {row["code"]: row["short_code"] for row in rows}
    assert marks["weigher"] == "SRT"
    assert marks["sort"] != "SRT"
    assert marks["custom_veewash_folder"] == "VFD"
    renamed = assign_short_codes([{"code": "attendant", "name": "VeeWash Folder", "short_code": None}])
    assert renamed[0]["short_code"] == "VFD"
    assert len(set(marks.values())) == 3


def test_propose_short_code_skips_a_taken_value():
    assert propose_short_code("fold", "Fold", set()) == "FLD"
    assert propose_short_code("fold", "Fold", {"FLD"}) != "FLD"


def test_catalog_read_does_not_change_the_schema_or_role_names():
    cursor = _CatalogCursor(has_short_code=False)
    catalog = {role["code"]: role for role in list_role_catalog(cursor, 1)}
    assert catalog["fold"]["name"] == "Fold"
    assert catalog["fold"]["code"] == "fold"
    assert catalog["fold"]["short_code"] == "FLD"
    selects = [statement for statement in cursor.statements if statement.lower().startswith("select")]
    assert selects
    assert all("short_code" not in statement.lower() for statement in selects)
    assert all("alter table" not in statement.lower() for statement in cursor.statements)


def test_saving_a_role_code_waits_for_the_migration_and_a_name_edit_does_not():
    cursor = _CatalogCursor(has_short_code=False)
    saved, err = update_role(cursor, 1, "fold", {"short_code": "FLD"})
    assert saved is None
    assert "migration" in err
    assert cursor.saved == []
    renamed, err = update_role(cursor, 1, "fold", {"name": "Folding"})
    assert err is None
    assert renamed["name"] == "Folding"
    assert renamed["code"] == "fold"
    assert "short_code" not in cursor.statements[-1].lower()
    assert "alter table" not in "\n".join(cursor.statements).lower()


def test_short_code_migration_is_explicit_and_does_not_touch_schedules_or_tasks():
    script = Path("backend/sql/weekly_schedule_roles_short_code_v1.sql").read_text(encoding="utf-8")
    body = "\n".join(line for line in script.splitlines() if not line.strip().startswith("--"))
    lowered = body.lower()
    assert "add column short_code" in lowered
    assert "update " not in lowered
    assert "delete " not in lowered
    assert "planned_weekly_schedule" not in lowered
    assert "drop column short_code" in script.lower()
