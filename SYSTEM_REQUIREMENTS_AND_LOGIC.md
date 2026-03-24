# LaundryOps System Requirements and Logic

## 1. Architecture
- Frontend: React (PWA-capable), mobile-first operations UI.
- Backend: Flask API.
- DB: Azure MySQL.
- Core data flow: Upload Batch Draft -> Review/Confirm -> Staging Operations -> Final Archive.

## 2. Core Data Zones
- `upload_batches`: batch headers (draft/confirmed/closed).
- `upload_batch_rows`: uploaded rows with row-level review status.
- `orders_staging`: live operational queue (pending/processed/checked/forced).
- `orders_final`: completed archive once both logistics + processing completion conditions are met.
- `checkout_log`: sent-to-rinse action log.

## 3. Status Model
- Logistics track (current implementation mixed in status values):
  - `AT_WASHPRO` (planned), `CHECKED_OUT`, `FORCED_CHECKOUT`.
- Processing track:
  - `PENDING`, `PROCESSED`, `ISSUE_REPORTED`.
- Batch row track (`upload_batch_rows.row_status`):
  - `ACCEPTED`, `OVERRIDDEN`, `REJECTED_DUPLICATE`, `NEEDS_ATTENTION`, `DELETED`.

## 4. Upload and Batch Logic
### 4.1 Upload Draft
- User uploads file and selects `batch_date`.
- System creates a draft batch and parses file rows into `upload_batch_rows`.
- Row classification:
  - `NEEDS_ATTENTION` if `date_clean < batch_date`.
  - `REJECTED_DUPLICATE` if duplicate in same upload.
  - `REJECTED_DUPLICATE` if identity already exists in active staging.
  - else `ACCEPTED`.

### 4.2 Batch Review Actions
- User can:
  - Edit row (override fields: date, name, weight/count, service, rush).
  - Delete row from batch.
  - Add new row to batch.
- Batch rows older than batch date remain `NEEDS_ATTENTION` unless corrected.

### 4.3 Confirm Batch
- Confirm applies accepted/overridden rows to staging.
- Reconciliation for existing staging rows not in new uploaded identity set:
  - If currently `PROCESSED`: mark forced checkout and move to final.
  - If currently pending-like: mark `FORCED_CHECKOUT` and keep in staging until processed.
- Confirm can block on unresolved `NEEDS_ATTENTION` unless force-confirm is used.

### 4.4 Same-Day/Next-Batch Rules
- New upload closes previous draft batch.
- Same-day re-upload replaces draft context (latest draft is active source).
- Previous batch remains for audit trail.

## 5. Rush Logic
- Row is `RUSH` if:
  - explicitly marked today/rush in upload transform, or
  - `date_clean == batch_date`.
- Otherwise `NON-RUSH`.

## 6. Identity and Duplicate Logic
- Identity key:
  - normalized name + normalized service + normalized measure.
- Measure normalization:
  - WF -> decimal 2 precision (lbs).
  - HD -> integer count.

## 7. Checkout Logic
- Individual/bulk checkout writes to `checkout_log` and updates staging status.
- Undo checkout supported.
- Sent-to-rinse counters are operational and can be batch-scoped in UI.

## 8. Orders Module Requirements
- Search by id/name.
- Filters: service/rush/status.
- Alphabet indexing.
- Inline edit/delete.
- Print action.
- Dashboard cards deep-link to Orders with pre-applied filters.

## 9. Dashboard Requirements
- Row 1: All orders total.
- Row 2: WF total + rush/non-rush split.
- Row 3: HD total + rush/non-rush split.
- Batch date label shows day + date.
- All cards clickable to Orders filtered view.

## 10. Mobile UX Shell Requirements
- Top bar on every mobile page:
  - Back icon.
  - Refresh icon.
- No bottom navigation (navigation via landing + back).
- Landing page is module-first entry point.

## 11. Attendance/Clock (Current Direction)
- Single primary clock action.
- Separate break flow.
- Optional rinse shift start/end capture.
- Geofence and alerts are configurable (MVP).

## 12. Next Planned Improvements
- Split logistics_status and processing_status into separate columns (recommended hardening).
- Add order activity event log table for full audit.
- Add role-based login with PIN + permissions per module.
- Add issue maintenance enhancements and linked external order reference URL.

## 13. Maintenance Module (New Requirement)
### 13.1 Objective
- Track routine and ad-hoc maintenance tasks with assignment, due dates, completion logs, and overdue notifications.

### 13.2 Core entities
- `maintenance_tasks`
  - task catalog (e.g., `Pit 1 Cleaning`, `Pit 2 Cleaning`, `Big Pit`, `Washer Cleaning`, `Dryer Cleaning`, `Roof Cleaning`, `Floor Mopping`, `Machine Cleaning`).
  - supports add/remove/deactivate.
- `maintenance_task_assignments`
  - task + assignee + due date + recurrence settings.
  - supports random/one-off assignment and repeating schedules.
- `maintenance_task_logs`
  - captures execution: employee name/id, date, day, start time, end time, notes, status, evidence optional.
  - supports boolean checkpoints (Pit1/Pit2/BigPit) and optional washer number.
- `maintenance_notifications`
  - generated reminders/escalations for due/overdue tasks.
  - recipient types: responsible employee + admin.

### 13.3 Screen behavior
- Maintenance landing:
  - `Assigned Tasks` (due today/overdue/upcoming).
  - `Ad-hoc Task Entry` (choose or type task, submit log immediately).
- Assignment workflow:
  - assign person, due date, recurrence pattern.
- Completion workflow:
  - enter start/end times, date, task-specific checkboxes, save log.

## 14. Inventory Module (New Requirement)
### 14.1 Objective
- Manage supplies and Washpro branded bag inventory with thresholds and task-driven counting.

### 14.2 Core entities
- `inventory_items`
  - item master: name, category (`SUPPLY`, `BAG`), vendor, unit, reorder threshold, active.
- `inventory_counts`
  - periodic stock counts (weekly for supplies, live sales for bags).
- `bag_sales`
  - per-sale records: date, customer name, type (drop-off/pickup-delivery), quantity, amount paid.
- `inventory_tasks`
  - task links for scheduled counting and reminders.

### 14.3 Rules
- Supplies: manual weekly count update.
- Bags: decrement on each sale entry.
- Threshold alerts: trigger when `on_hand <= reorder_threshold`.

## 15. Authentication and RBAC (New Requirement)
### 15.1 Objective
- Add secure login and role-based authorization by module and action.

### 15.2 Core entities
- `users`
  - username, password hash (bcrypt/argon2), active, employee link optional.
- `roles`
  - admin, operations, front_desk, maintenance, etc.
- `permissions`
  - module-level and function-level permissions.
- `user_roles` / `role_permissions`
  - many-to-many mappings.
- `auth_sessions` (or JWT + refresh token table)
  - login session control + revoke support.
- `auth_audit_log`
  - login/logout/failed attempts/permission denials.

### 15.3 Security baseline
- Store hashed passwords only.
- Enforce account lockout/rate-limit after repeated failures.
- Server-side permission checks on every protected API.
- Hide/disable unauthorized UI actions.

## 16. Implementation Phasing (Recommended)
1. Maintenance backend schema + CRUD + assignment/log APIs.
2. Maintenance UI (assigned + ad-hoc + history).
3. Inventory schema + count/sales APIs.
4. Inventory UI + threshold alerts.
5. Login + RBAC backend, then frontend guards and role-based navigation.
6. Notifications pipeline (push first, SMS second).
