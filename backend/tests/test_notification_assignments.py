"""Management notification recipients are explicit, and inactive routing stays legacy."""

from pathlib import Path

from backend.notification_assignments import (
    management_dispatch_recipients,
    resolve_assigned_recipients,
    save_management_assignment,
    set_routing_active,
)
from backend.notification_catalog import LEGACY_ROUTING, management_event


LOST = "lost_found.item_reported"


class Mem:
    def __init__(self):
        self.users = {
            15: {"organization_id": 3, "active": 1, "username": "veeadmin", "display_name": "Muhammad Najeeb"},
            16: {"organization_id": 3, "active": 1, "username": "francis", "display_name": "Francis"},
            41: {"organization_id": 3, "active": 1, "username": "najeeb.abaumer", "display_name": "Najeeb Abaumer"},
            50: {"organization_id": 3, "active": 0, "username": "former", "display_name": "Former Employee"},
            90: {"organization_id": 9, "active": 1, "username": "other", "display_name": "Other Org"},
        }
        self.recipients = {}
        self.settings = {}
        self.activation = {}
        self.audit = []
        self.delivery = [{"id": 67, "user_id": 41}]
        self.sqls = []
        self._one = None
        self._all = []

    def execute(self, sql, params=None):
        text = " ".join(sql.split())
        self.sqls.append(text)
        params = tuple(params or ())
        self._one = None
        self._all = []
        if "notification_delivery_log" in text or "user_roles" in text or "employee_mobile_pin_access" in text:
            raise AssertionError(text)
        if text.startswith("SELECT management_routing_active"):
            org = params[0]
            if org in self.activation:
                self._one = {"management_routing_active": self.activation[org]}
        elif text.startswith("SELECT enabled FROM"):
            key = (params[0], params[1])
            if key in self.settings:
                self._one = {"enabled": self.settings[key]}
        elif text.startswith("SELECT r.event_key"):
            org = params[0]
            rows = []
            for (row_org, event), people in self.recipients.items():
                if row_org != org:
                    continue
                for uid in people:
                    user = self.users.get(uid)
                    if not user or user["organization_id"] != org:
                        continue
                    rows.append(
                        {
                            "event_key": event,
                            "user_id": uid,
                            "username": user["username"],
                            "display_name": user["display_name"],
                            "active": user["active"],
                        }
                    )
            self._all = rows
        elif text.startswith("SELECT event_key, enabled"):
            org = params[0]
            self._all = [
                {"event_key": event, "enabled": enabled}
                for (row_org, event), enabled in self.settings.items()
                if row_org == org
            ]
        elif text.startswith("INSERT INTO notification_routing_activation"):
            self.activation[params[0]] = params[1]
        elif text.startswith("SELECT r.user_id"):
            org, event = params
            rows = []
            for uid in self.recipients.get((org, event), {}):
                user = self.users.get(uid)
                if user and user["organization_id"] == org and user["active"]:
                    rows.append({"user_id": uid})
            self._all = rows
        elif text.startswith("SELECT id, username, display_name"):
            org = params[0]
            needle = str(params[3] or "").lower()
            self._all = [
                {"id": uid, "username": user["username"], "display_name": user["display_name"]}
                for uid, user in self.users.items()
                if user["organization_id"] == org
                and user["active"]
                and (
                    not needle
                    or needle in user["username"].lower()
                    or needle in user["display_name"].lower()
                )
            ][:20]
        elif text.startswith("SELECT id, active FROM users"):
            org, ids = params[0], params[1:]
            self._all = [
                {"id": uid, "active": self.users[uid]["active"]}
                for uid in ids
                if uid in self.users and self.users[uid]["organization_id"] == org
            ]
        elif text.startswith("SELECT user_id FROM"):
            org, event = params
            self._all = [{"user_id": uid} for uid in self.recipients.get((org, event), {})]
        elif text.startswith("DELETE FROM notification_category_recipients"):
            self.recipients[(params[0], params[1])] = {}
        elif text.startswith("INSERT INTO notification_category_recipients"):
            org, event, uid, actor = params
            self.recipients.setdefault((org, event), {})[uid] = actor
        elif text.startswith("INSERT INTO notification_category_settings"):
            self.settings[(params[0], params[1])] = params[2]
        elif text.startswith("INSERT INTO notification_assignment_audit"):
            self.audit.append(
                {
                    "organization_id": params[0],
                    "event_key": params[1],
                    "action": params[2],
                    "actor_user_id": params[3],
                    "detail_json": params[4],
                }
            )

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._all)


def _tables_exist(_cursor, _name):
    return True


def test_multiple_recipients_can_be_saved_and_reloaded(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    mem.activation[3] = 1
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15, 16, 15], enabled=True, actor_user_id=15
    )
    assert resolve_assigned_recipients(mem, 3, LOST) == {15, 16}
    assert mem.recipients[(3, LOST)].keys() == {15, 16}


def test_a_recipient_can_be_removed(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    mem.activation[3] = 1
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15, 16], enabled=True, actor_user_id=15
    )
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[16], enabled=True, actor_user_id=15
    )
    assert resolve_assigned_recipients(mem, 3, LOST) == {16}


def test_finance_without_assignment_is_not_a_recipient(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    mem.activation[3] = 1
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15], enabled=True, actor_user_id=15
    )
    chosen = resolve_assigned_recipients(mem, 3, LOST)
    assert chosen == {15}
    assert 41 not in chosen


def test_empty_list_sends_nobody_and_missing_rows_do_not_broadcast(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    mem.activation[3] = 1
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[], enabled=True, actor_user_id=15
    )
    assert resolve_assigned_recipients(mem, 3, LOST) == set()
    assert management_dispatch_recipients(mem, 3, LOST) == set()
    untouched = Mem()
    untouched.activation[3] = 1
    assert resolve_assigned_recipients(untouched, 3, LOST) == set()


def test_disabled_category_and_inactive_user_are_excluded(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    mem.activation[3] = 1
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15], enabled=False, actor_user_id=15
    )
    assert resolve_assigned_recipients(mem, 3, LOST) == set()
    mem.recipients[(3, LOST)][50] = 15
    mem.settings[(3, LOST)] = 1
    assert 50 not in resolve_assigned_recipients(mem, 3, LOST)


def test_other_organization_and_inactive_user_cannot_be_assigned(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    try:
        save_management_assignment(
            mem, organization_id=3, event_key=LOST, user_ids=[90], enabled=True, actor_user_id=15
        )
        raised = False
    except Exception as ex:
        raised = ex.code == "outside_organization"
    assert raised
    try:
        save_management_assignment(
            mem, organization_id=3, event_key=LOST, user_ids=[50], enabled=True, actor_user_id=15
        )
        raised = False
    except Exception as ex:
        raised = ex.code == "inactive_user"
    assert raised
    assert mem.recipients == {}


def test_inactive_routing_keeps_the_previous_rules(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    mem.recipients[(3, LOST)] = {15: 15}
    assert management_dispatch_recipients(mem, 3, LOST) is LEGACY_ROUTING


def test_personal_and_unsupported_events_are_not_management_lists():
    assert management_event("finance.drc.mobile_section.returned") is None
    assert management_event("clock_in_reminder") is None
    assert management_event("document_compliance") is None
    assert management_event("scheduling.published") is None
    assert management_event("performance.alert") is None
    assert management_event("quality.alert") is None


def test_save_audits_the_actor_and_preserves_delivery_history(monkeypatch):
    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    before = list(mem.delivery)
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15, 16], enabled=True, actor_user_id=15
    )
    assert mem.delivery == before
    assert mem.audit[-1]["actor_user_id"] == 15
    assert mem.audit[-1]["action"] == "assignment_saved"
    assert "user_roles" not in " ".join(mem.sqls)
    assert "notification_delivery_log" not in " ".join(mem.sqls)


def test_dispatch_dedupes_and_honors_push_opt_out(monkeypatch):
    from backend.notification_service import dispatch_notification_event

    sent = []

    def send(ids, title, body, **kwargs):
        sent.append(list(ids))
        return True, None

    class Cursor:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchone(self):
            if "user_notification_preferences" in self.sql:
                return {"email_out": 1, "push_out": self.push_out, "sms_out": 1, "whatsapp_out": 0}
            return {"id": 4}

        def fetchall(self):
            return []

        push_out = 1

    monkeypatch.setattr("backend.onesignal_client.send_push_to_external_user_ids", send)
    monkeypatch.setattr("backend.ta_helpers.table_exists", lambda *_a, **_k: False)
    cursor = Cursor()
    dispatch_notification_event(
        cursor,
        organization_id=3,
        event_key=LOST,
        title="VeeWash",
        body="Issue",
        channels=["push"],
        recipient_user_ids=[15, 15, 16],
    )
    assert sent == [["lo-3-15"], ["lo-3-16"]]
    sent.clear()
    cursor.push_out = 0
    dispatch_notification_event(
        cursor,
        organization_id=3,
        event_key=LOST,
        title="VeeWash",
        body="Issue",
        channels=["push"],
        recipient_user_ids=[41],
    )
    assert sent == []


def test_activated_lost_found_uses_assignments_not_roles(monkeypatch):
    from backend.lost_found import notify_found_item

    seen = {}

    def dispatch(_cursor, **kwargs):
        seen.update(kwargs)
        return {"ok": True, "sent": {"push": 1}}

    class Cursor:
        def execute(self, *_a, **_k):
            return None

        def fetchone(self):
            return {"id": 1}

        def fetchall(self):
            return []

    def reviewers(*_a, **_k):
        raise AssertionError("role recipients were used")

    monkeypatch.setattr("backend.lost_found.table_exists", lambda *_a, **_k: True)
    monkeypatch.setattr("backend.notification_service.dispatch_notification_event", dispatch)
    monkeypatch.setattr(
        "backend.notification_assignments.management_dispatch_recipients",
        lambda *_a, **_k: {15},
    )
    monkeypatch.setattr("backend.lost_found.issue_reviewer_user_ids", reviewers)
    notify_found_item(Cursor(), 3, {"id": 8, "employee_name": "Ana", "report_category": "orphan"})
    assert seen["recipient_user_ids"] == {15}
    assert seen["organization_id"] == 3


def test_routing_activation_is_explicit_reversible_and_isolated(monkeypatch):
    from backend.notification_assignments import management_catalog

    monkeypatch.setattr("backend.ta_helpers.table_exists", _tables_exist)
    mem = Mem()
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15], enabled=True, actor_user_id=15
    )
    assert management_dispatch_recipients(mem, 3, LOST) is LEGACY_ROUTING
    try:
        set_routing_active(mem, organization_id=3, active=True, actor_user_id=15, confirm_incomplete=False)
        refused = False
    except Exception as ex:
        refused = ex.code == "incomplete_configuration"
        assert any(row["label"] == "PIN Issues — Issue Reported" for row in ex.details["empty_categories"]) is False
        assert ex.details["empty_categories"]
    assert refused
    assert management_dispatch_recipients(mem, 3, LOST) is LEGACY_ROUTING

    set_routing_active(mem, organization_id=3, active=True, actor_user_id=15, confirm_incomplete=True)
    assert resolve_assigned_recipients(mem, 3, LOST) == {15}
    assert 41 not in resolve_assigned_recipients(mem, 3, LOST)
    assert management_dispatch_recipients(mem, 9, LOST) is LEGACY_ROUTING

    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[], enabled=True, actor_user_id=15
    )
    assert resolve_assigned_recipients(mem, 3, LOST) == set()
    save_management_assignment(
        mem, organization_id=3, event_key=LOST, user_ids=[15, 16], enabled=False, actor_user_id=15
    )
    assert resolve_assigned_recipients(mem, 3, LOST) == set()

    set_routing_active(mem, organization_id=3, active=False, actor_user_id=15)
    assert management_dispatch_recipients(mem, 3, LOST) is LEGACY_ROUTING
    actions = [row["action"] for row in mem.audit]
    assert "routing_activated" in actions
    assert "routing_deactivated" in actions
    assert all(row["actor_user_id"] == 15 for row in mem.audit if row["action"].startswith("routing_"))
    assert mem.delivery == [{"id": 67, "user_id": 41}]
    catalog = management_catalog(mem, 3)
    assert catalog["management_routing_active"] is False
    issue = next(
        category
        for module in catalog["modules"]
        if module["label"] == "PIN Issues"
        for category in module["categories"]
    )
    assert issue["label"] == "Issue Reported"
    assert "Equipment" in issue["description"]


def test_assignment_migration_does_not_touch_existing_records():
    sql = Path("backend/sql/notification_assignments_v1.sql").read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in sql.splitlines() if line.strip() and not line.strip().startswith("--")
    )
    assert executable.count("CREATE TABLE IF NOT EXISTS") == 4
    assert "DROP TABLE" not in executable.upper()
    assert "user_roles" not in executable
    assert "user_notification_preferences" not in executable
    assert "notification_delivery_log" not in executable
    assert "employee_mobile_pin_access" not in executable
    routes = Path("backend/notification_routes.py").read_text(encoding="utf-8")
    assignments = Path("backend/notification_assignments.py").read_text(encoding="utf-8")
    assert "ensure_assignment_tables" not in routes
    assert "ensure_assignment_tables" not in assignments
    assert "CREATE TABLE" not in routes
    assert "CREATE TABLE" not in assignments
    assert 'MIGRATION_FILE = "backend/sql/notification_assignments_v1.sql"' in assignments
    assert "MIGRATION_FILE" in routes
    assert routes.count("require_admin(cursor)") >= 3
