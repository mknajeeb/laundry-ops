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
