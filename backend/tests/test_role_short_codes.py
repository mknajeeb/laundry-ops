"""Three-character role codes stay unique without rewriting role ids."""

from backend.weekly_schedule_roles import assign_short_codes, default_role_catalog, propose_short_code


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
