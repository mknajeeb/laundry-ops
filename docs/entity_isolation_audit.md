# Entity isolation audit

WashPro, WashMate, and VeeWash are **separate business entities**. They share one software platform and database schema, but business records must not mix unless explicitly marked `shared`.

## Isolation layers

| Layer | Mechanism | Status |
|-------|-----------|--------|
| Login tenant | `organizations.id` + slug (`washpro`, `washmate`, `veewash`) | Implemented |
| Worker entity | `payroll_worker_profiles.business_entity` + derived flags | Implemented (migration `backend/sql/business_entity_v1.sql`) |
| Schedule shift entity | `planned_weekly_schedule_entries.employer_affiliation` | Implemented (`washpro`, `washmate`, `veewash`, `rinse_exclusive`) |
| Weekly schedule tabs | Entity tabs filtered by worker + shift entity | Implemented |
| Bulk shift moves | Per-entry entity validation; skips cross-entity rows | Implemented |
| Rinse bag ownership | `rinse_bag_operational_owner.owner_organization_id` | Existing cross-org guards |

## Entity tabs by tenant login

| Org slug | Default entity tabs | Combined (admin) |
|----------|--------------------|------------------|
| `washpro` | WashPro, Rinse Exclusive | Yes (privileged) |
| `washmate` | WashMate | Yes (privileged) |
| `veewash` | VeeWash | Yes (privileged) |

Workers with affiliation **`none`** never appear on entity-specific tabs. They may appear only on **Combined (Admin)** for cleanup.

## Legacy naming fix

Historical shift rows stored `employer_affiliation = veewash` on the WashPro org. That value now normalizes to **`washpro`** on non-`veewash` orgs. The VeeWash **tenant** and VeeWash **entity** are distinct concepts.

## Remaining gaps (follow-up)

These areas are org-scoped (`organization_id`) but not yet split by business entity:

- Payroll cycles / payout batches
- Employee productivity aggregates
- Today's workload / shift monitor (except rinse vendor + operational owner guards)
- Daily shift roster
- Time clock / shift sessions

Add `business_entity_id` to those modules when payroll and productivity must be legally separated per entity within one login tenant.

## Regression tests

See `backend/tests/test_business_entity_isolation.py`.

## Operational checklist

Before shipping entity-sensitive features, confirm:

1. Query filters by `organization_id = current tenant`
2. UI filters by active entity tab / worker affiliation
3. Bulk actions validate worker entity vs destination entity
4. Combined view is labeled admin-only and not used for normal ops
