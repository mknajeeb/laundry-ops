#!/usr/bin/env python3
"""Inventory v2.5 end-to-end smoke test (local backend + Azure DB)."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Load repo-root .env
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from backend.db import get_db
from backend.ta_helpers import table_exists

SMOKE_PORT = int(os.getenv("INVENTORY_SMOKE_PORT", "8010"))
BASE = f"http://127.0.0.1:{SMOKE_PORT}"
ADMIN_USER_ID = int(os.getenv("INVENTORY_SMOKE_ADMIN_ID", "1"))  # washpro admin
FLOOR_USER_ID = int(os.getenv("INVENTORY_SMOKE_FLOOR_ID", "5"))  # Muhammad FRONT_DESK


class SmokeFailure(Exception):
    pass


def log(step: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    msg = f"[{mark}] {step}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def mint_token(user_id: int) -> str:
    token = uuid.uuid4().hex
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO auth_sessions (user_id, token, expires_at, revoked, created_at, last_seen_at)
        VALUES (%s, %s, %s, FALSE, NOW(), NOW())
        """,
        (user_id, token, datetime.utcnow() + timedelta(hours=2)),
    )
    conn.commit()
    cur.close()
    conn.close()
    return token


def api(token: str, method: str, path: str, **kwargs):
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{BASE}{path}"
    return requests.request(method, url, headers=headers, timeout=120, **kwargs)


def wait_for_server(proc: subprocess.Popen, timeout: float = 180.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        if proc.poll() is not None:
            raise SmokeFailure(f"Backend exited early (code {proc.returncode})")
        try:
            r = requests.get(f"{BASE}/auth/me", timeout=30)
            if r.status_code in (401, 200):
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise SmokeFailure("Backend did not become ready in time")


def start_backend() -> subprocess.Popen:
    env = os.environ.copy()
    env["PORT"] = str(SMOKE_PORT)
    env["FLASK_DEBUG"] = "0"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "run.py")],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_server(proc)
    return proc


def stop_backend(proc: subprocess.Popen | None) -> None:
    if not proc or proc.poll() is not None:
        return
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def db_counts(org_id: int) -> dict:
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    out = {"categories": 0, "vendors": 0, "items": 0}
    if table_exists(cur, "inventory_categories"):
        cur.execute("SELECT COUNT(*) AS c FROM inventory_categories WHERE organization_id = %s", (org_id,))
        out["categories"] = int((cur.fetchone() or {}).get("c") or 0)
    if table_exists(cur, "inventory_vendors"):
        cur.execute("SELECT COUNT(*) AS c FROM inventory_vendors WHERE organization_id = %s", (org_id,))
        out["vendors"] = int((cur.fetchone() or {}).get("c") or 0)
    if table_exists(cur, "inventory_items"):
        if table_exists(cur, "inventory_items") and _has_col(cur, "organization_id"):
            cur.execute("SELECT COUNT(*) AS c FROM inventory_items WHERE organization_id = %s", (org_id,))
        else:
            cur.execute("SELECT COUNT(*) AS c FROM inventory_items")
        out["items"] = int((cur.fetchone() or {}).get("c") or 0)
    cur.close()
    conn.close()
    return out


def _has_col(cur, col: str) -> bool:
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM information_schema.columns
        WHERE table_schema = DATABASE() AND table_name = 'inventory_items' AND column_name = %s
        """,
        (col,),
    )
    return int((cur.fetchone() or {}).get("c") or 0) > 0


def main() -> int:
    results: list[tuple[str, bool, str]] = []
    proc: subprocess.Popen | None = None
    admin_token = mint_token(ADMIN_USER_ID)
    floor_token = mint_token(FLOOR_USER_ID)

    try:
        # 1–3: restart twice, bootstrap, verify no duplicate counts
        proc = start_backend()
        r = api(admin_token, "GET", "/inventory/bootstrap")
        if r.status_code != 200:
            raise SmokeFailure(f"bootstrap failed: {r.status_code} {r.text[:200]}")
        counts1 = db_counts(1)
        log("Restart 1 + ADMIN bootstrap", True, json.dumps(counts1))

        stop_backend(proc)
        time.sleep(1)
        proc = start_backend()
        r = api(admin_token, "GET", "/inventory/bootstrap")
        counts2 = db_counts(1)
        dup_ok = counts1 == counts2
        log("Restart 2 — counts stable", dup_ok, f"{counts1} -> {counts2}")
        results.append(("migration idempotency", dup_ok, ""))

        boot = r.json()
        items = boot.get("items") or []
        if not items:
            raise SmokeFailure("No inventory items after bootstrap")
        test_item = items[0]
        item_id = test_item["id"]
        on_hand_before = float(test_item.get("current_on_hand") or 0)
        counted_qty = on_hand_before  # no variance

        # 4–5: stock check submit + duplicate blocked
        api(admin_token, "POST", "/inventory/stock-check/draft", json={
            "lines": [{"item_id": item_id, "counted_qty": counted_qty}],
        })
        sub = api(admin_token, "POST", "/inventory/stock-check/submit", json={
            "lines": [{"item_id": item_id, "counted_qty": counted_qty}],
            "oneshot": True,
        })
        sub_ok = sub.status_code == 200
        log("Stock check submit", sub_ok, sub.text[:120])
        dup = api(admin_token, "POST", "/inventory/stock-check/submit", json={
            "lines": [{"item_id": item_id, "counted_qty": counted_qty}],
        })
        err = (dup.json().get("error") or "").lower()
        dup_blocked = dup.status_code == 409 and ("no draft" in err or "already submitted" in err)
        log("Duplicate stock check blocked", dup_blocked, dup.text[:120])
        results.append(("stock check once + dup blocked", sub_ok and dup_blocked, ""))

        # refresh item on_hand after stock check (should be unchanged if same count)
        item_res = api(admin_token, "GET", "/inventory/items", params={"active_only": "1"})
        item_row = next((i for i in item_res.json() if i["id"] == item_id), {})
        on_hand_after_check = float(item_row.get("current_on_hand") or 0)

        # 6–9: PO partial receive
        vendors = api(admin_token, "GET", "/inventory/vendors").json()
        vendor_id = vendors[0]["id"] if vendors else None
        po_payload = {
            "status": "ORDERED",
            "vendor_id": vendor_id,
            "order_date": datetime.utcnow().date().isoformat(),
            "lines": [{"item_id": item_id, "qty_ordered": 10, "unit_cost": 5.0}],
        }
        po = api(admin_token, "POST", "/inventory/orders", json=po_payload)
        po_ok = po.status_code == 200
        order_id = po.json().get("id")
        log("Create PO", po_ok, f"order_id={order_id}")
        order_detail = api(admin_token, "GET", "/inventory/orders", params={"limit": 5}).json()
        order = next((o for o in order_detail if o["id"] == order_id), None)
        line_id = order["lines"][0]["id"] if order and order.get("lines") else None

        recv1 = api(admin_token, "POST", f"/inventory/orders/{order_id}/receive", json={
            "lines": [{"line_id": line_id, "qty_received": 4}],
        })
        recv1_ok = recv1.status_code == 200
        log("Partial receive (4)", recv1_ok, recv1.text[:120])

        item_res2 = api(admin_token, "GET", "/inventory/items", params={"active_only": "1"})
        item_row2 = next((i for i in item_res2.json() if i["id"] == item_id), {})
        on_hand_after_partial = float(item_row2.get("current_on_hand") or 0)
        expected_on_hand = on_hand_after_check + 4
        qty_ok = abs(on_hand_after_partial - expected_on_hand) < 0.001
        log("On-hand +4 only", qty_ok, f"{on_hand_after_check} -> {on_hand_after_partial} (expected {expected_on_hand})")

        recv2 = api(admin_token, "POST", f"/inventory/orders/{order_id}/receive", json={
            "lines": [{"line_id": line_id, "qty_received": 4}],
        })
        zero_blocked = recv2.status_code == 400 and "no new quantities" in (recv2.json().get("error") or "").lower()
        log("Zero-delta receive blocked", zero_blocked, recv2.text[:120])
        results.append(("PO partial receive integrity", po_ok and recv1_ok and qty_ok and zero_blocked, ""))

        # 10–12: FRONT_DESK API restrictions
        floor_boot = api(floor_token, "GET", "/inventory/bootstrap")
        floor_ok = floor_boot.status_code == 200
        tier = floor_boot.json().get("role_tier")
        tier_ok = tier == "floor"
        log("FRONT_DESK bootstrap tier=floor", tier_ok, f"tier={tier}")

        blocked_paths = [
            ("GET", "/inventory/orders"),
            ("GET", "/inventory/reports"),
            ("POST", "/inventory/categories", {"name": "Smoke Cat"}),
            ("PUT", "/inventory/settings/variance-threshold", {"variance_threshold": 5}),
            ("GET", "/inventory/vendors", {"with_stats": "1"}),
            ("GET", "/inventory/reorder-suggestions"),
        ]
        allowed_reads = [
            ("GET", "/inventory/categories"),
        ]
        api_blocks = 0
        for entry in blocked_paths:
            method, path = entry[0], entry[1]
            payload = entry[2] if len(entry) > 2 else None
            kwargs = {}
            if payload is not None:
                if method == "GET":
                    kwargs["params"] = payload
                else:
                    kwargs["json"] = payload
            resp = api(floor_token, method, path, **kwargs)
            if resp.status_code in (401, 403):
                api_blocks += 1
        block_ok = api_blocks == len(blocked_paths)
        read_ok = all(api(floor_token, method, path).status_code == 200 for method, path in allowed_reads)
        log("FRONT_DESK blocked from PO/reports/settings APIs", block_ok, f"{api_blocks}/{len(blocked_paths)} returned 403/401")
        log("FRONT_DESK can read categories (stock check)", read_ok, "")
        results.append(("FRONT_DESK API blocks", floor_ok and tier_ok and block_ok and read_ok, ""))

        # 13: dashboard values
        dash = api(admin_token, "GET", "/inventory/dashboard")
        dash_ok = dash.status_code == 200
        kpis = dash.json().get("kpis") or {}
        fin_ok = (
            kpis.get("inventory_value") is not None
            and kpis.get("this_week_purchases") is not None
            and kpis.get("pending_purchase_orders") is not None
        )
        floor_dash = api(floor_token, "GET", "/inventory/dashboard")
        floor_kpis = floor_dash.json().get("kpis") or {}
        floor_fin_hidden = floor_kpis.get("inventory_value") is None and floor_kpis.get("this_week_purchases") is None
        log("ADMIN dashboard KPIs present", fin_ok, json.dumps({k: kpis.get(k) for k in ("inventory_value", "this_week_purchases", "pending_purchase_orders")})[:120])
        log("FRONT_DESK dashboard hides $ KPIs", floor_fin_hidden, "")
        results.append(("dashboard KPIs", dash_ok and fin_ok and floor_fin_hidden, ""))

        # 14: mobile padding static check
        stock_tab = (ROOT / "frontend/src/components/inventory/StockCheckTab.jsx").read_text(encoding="utf-8")
        mobile_ok = "pb: { xs: 14" in stock_tab and "StickyActionBar" in (ROOT / "frontend/src/components/inventory/InventoryShared.jsx").read_text(encoding="utf-8")
        inv_page = (ROOT / "frontend/src/pages/InventoryPage.jsx").read_text(encoding="utf-8")
        floor_tabs_ok = 'canAccessInventoryTab(roleTier, t.key, hasPerm)' in inv_page and '"dashboard"' in inv_page and '"check"' in inv_page
        qty_stepper_ok = "QtyStepper" in (ROOT / "frontend/src/components/inventory/InventoryShared.jsx").read_text(encoding="utf-8")
        log("Mobile Stock Check bottom padding (xs:14)", mobile_ok, "")
        log("FRONT_DESK UI tabs: dashboard + check only (code)", floor_tabs_ok, "canAccessInventoryTab gates orders/reports/settings")
        log("QtyStepper +/- on stock check", qty_stepper_ok, "")
        results.append(("mobile + UI role tabs", mobile_ok and floor_tabs_ok and qty_stepper_ok, ""))

    except SmokeFailure as e:
        log("SMOKE TEST", False, str(e))
        return 1
    finally:
        stop_backend(proc)

    failed = [r for r in results if not r[1]]
    print("\n=== SUMMARY ===")
    for name, ok, _ in results:
        print(f"  {'✓' if ok else '✗'} {name}")
    if failed:
        print(f"\n{len(failed)} check(s) failed.")
        return 1
    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
