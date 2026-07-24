# Operations Mobile Redesign — Roadmap

Living plan for employee PIN-hub workflows and related manager setup.
Do **not** fold new scope into completed commits; each phase ships separately.

---

## Status snapshot

| Phase | Scope | Status |
|-------|--------|--------|
| 0 | Shared ops mobile primitives | **Done** (pushed earlier) |
| 1 | PIN launcher + Lock + Clock tile | **Done** |
| 2 | Full-screen Switch Role | **Done** |
| 3 | Tasks mobile checklist (presentation) | **Done** |
| 4 | Floor Inventory Count flow (presentation) | **Done** |
| **5A** | Clock setting; Stock Back→PIN fix; Role→Category order | **Done (local only)** |
| **5B** | Maintenance weekday assignment + submission | **Done (local only)** |
| **5C** | Employee role/category authorization | **Not started** (roadmap below) |
| **5D** | Lightweight Inventory Count (assignment + APIs) | **Not started** |
| **5E** | Mobile Revenue and Cost entry | **Not started** (roadmap below) |
| **5F** | Inventory purchasing + finance integration | **Not started** |

### Phase 5A — frozen

- **Commit:** `0e797ddee4a50294a3ade9c9440b031ec738708d`
- **Message:** Fix mobile clock controls, stock return flow, and role selection
- **Push:** not pushed (`main` ahead of `origin/main` by this commit until explicitly approved)
- **Rule:** Do not amend, squash, or mix later requirements into this commit.

---

## Revised implementation sequence

### Phase 5B — Maintenance assignments and submissions

Weekday assignee, daily checklist snapshot, employee submit → compact confirmation, manager expandable review, in-app submission notification.  
**Out of scope here:** role/category auth, inventory data model, revenue/cost.

Do not amend Phase 5A (`0e797dde`) when landing 5B.

### Phase 5C — Employee role/category authorization

User-specific **allowed role/category combinations** (not independent role + category lists).  
Must land before heavy reliance on Role data for productivity reporting.  
See [Requirement 1](#requirement-1--user-specific-role-and-category-combinations).

### Phase 5D — Lightweight Inventory Count

Weekday assignment, dedicated lightweight floor APIs, category drill-down, compact counts, notes, immutable submission, manager notification/review.  
Do not load the full manager Inventory app into the PIN flow.

### Phase 5E — Mobile Revenue and Cost Entry

Mobile-first operational entry with **section-level** permissions and assignments; separate from full finance/P&L access.  
See [Requirement 2](#requirement-2--revenue-and-cost-module-for-mobile-users).

### Phase 5F — Inventory Purchasing and Finance Integration

Vendor, pricing, receiving, expense, and P&L integration **after** the mobile count workflow (5D) is stable.  
Analytics / Rinse supply-use comparison remains later still if needed.

---

## Requirement 1 — User-specific role and category combinations

**Phase:** 5C  
**Problem:** A shared org-wide list of roles and categories is not enough. Independent “allowed roles” + “allowed categories” lists incorrectly permit cross products (e.g. Operator — DHS when only Operator — Rinse WF and Folding — DHS were intended).

### Correct model

```
Employee
  → Allowed work assignments = set of (category, role) combinations
```

Examples:

| Employee   | Allowed combinations |
|------------|----------------------|
| Jennifer   | Operator — Rinse WF; Folding — Rinse WF |
| Paola      | Folding — Rinse WF; Folding — DHS |
| Alec       | Operator — Rinse WF; Operator — Rinse HD; Operator — Drop Off |
| Supervisor | All combinations |

### Manager setup (People)

Per employee, under **Allowed Work Assignments**, a category × role matrix, e.g.:

| Category  | Operator | Folding |
|-----------|----------|---------|
| Rinse WF  | ☑        | ☑       |
| Rinse HD  | ☑        | ☐       |
| DHS       | ☐        | ☑       |
| Drop Off  | ☑        | ☐       |

Controls:

- **Allow all assignments**
- **Clear all**
- Empty-state warning when **no** combinations are assigned

Rules:

- Do **not** infer permission from the employee’s current punch/role alone.
- Managers with appropriate permission may assign all combinations.
- New employees: do **not** auto-grant all combinations unless explicitly selected during onboarding.
- Existing employees: safe migration/default — **preserve currently available combinations** until management customizes (do not suddenly empty the set).

### Employee Switch Role flow

Keep presentation order from 5A: **Role → Category**.

- Step 1: only roles that appear in at least one allowed combination.
- Step 2: only categories allowed for the selected role.
- **Hide** unavailable combinations (do not show disabled chips).
- Current combination stays visible even if later removed from the allow-list, until the employee changes away or clocks out.
- Selecting the exact current combination remains a **no-op** (no API, no segment, no toast).
- **Backend must validate** the selected combination; frontend filtering is not sufficient.

### Audit

Record manager changes to allowed combinations:

- Employee
- Combination added or removed
- Changed by
- Changed at

Must **not** rewrite historical attendance segments.

### Suggested deliverables (5C)

- People UI: Allowed Work Assignments matrix + allow-all / clear-all / empty warning
- Persistence + migration for existing employees
- Selection-tree / switch-role API filtered + server-side enforcement
- Mobile Role flow consumes filtered tree only
- Audit log for allow-list edits
- Tests for cross-product prevention, current-combo grandfathering, no-op current selection

---

## Requirement 2 — Revenue and Cost module for mobile users

**Phase:** 5E  
**Problem:** Revenue & Cost should become mobile-first, but mobile entry must **not** imply full finance access.

### Two access layers

**1. Mobile data-entry users**

- Enter operational figures for an assigned date/sections (e.g. Self Service Cash/Card, Drop Off Cash/Card, Rinse WF volume, Rinse HD orders/revenue, Commercial volume, assigned operational cost lines).
- Must **not** automatically see: full company P&L, payroll costs, landlord expenses, bank info, historical finance dashboards, profit margins, sensitive vendor pricing, other locations’ revenue.

**2. Finance / manager users**

- Review, correct/reject, approve the day
- Trends/reports and broader cost/profitability per existing permissions

### PIN workflow

Tile: **Revenue & Cost** — only when:

- Module enabled for the org
- User has mobile entry permission
- User is assigned to the date/location when assignments are required

```
PIN → Revenue & Cost → Confirm date → Enter assigned sections
  → Review totals → Submit → Submitted → Done
```

Do **not** embed the desktop finance dashboard in the PIN workflow.

### Mobile entry UX

- Compact sections only (org-enabled + user-assigned)
- Numeric keyboard, en-US currency formatting, large touch inputs
- Autosave draft
- One sticky **Review Submission** / **Submit Daily Report**
- No large KPI cards during entry

Example sections (illustrative): Self Service, Drop Off, Rinse (WF pounds / HD orders / HD revenue), Commercial (location pounds).

### User-specific section permissions

Granular, not “PIN hub unlock ⇒ finance.” Example matrix:

| Permission | Meaning |
|------------|---------|
| Self Service revenue | Enter SS cash/card |
| Drop Off revenue | Enter DO cash/card |
| Rinse revenue | Enter WF/HD operational inputs |
| Commercial revenue | Enter commercial pounds (category-level if needed) |
| Operating costs | Enter assigned cost lines |
| Review submissions | Manager review |
| Approve submissions | Approve day |
| View reports | Trends / broader reports |

### Assignment model

Weekday and/or date-specific; optional different users per section; a day may have no floor assignee (management owns it).

**Ownership key to prevent competing submissions:**

```
organization_id + business_date + revenue_cost_section
```

### Submission and manager review

Employee after submit: compact confirmation only (date + submitted-at); no edit unless rejected/reopened.

Manager: notification + collapsed row → expand for values, totals, submitter, time, missing sections, notes, optional ops-data comparison.

Manager actions (auditable): **Approve** · **Reject with reason** · **Return for correction**.  
Avoid silent manager edits.

### Calculations

Employees enter operational **inputs**; existing formulas compute revenue (e.g. commercial pounds × rate + charges; Rinse WF tier rules).  
All calculations **revalidated on the backend**.

### Suggested deliverables (5E)

- Mobile permission model + People/settings UI
- Weekday/date/section assignment
- Lightweight PIN tile + entry flow + draft + immutable submit
- Manager notification, expandable review, approve/reject/return
- Backend calc validation + ownership locking per section/date
- Explicit separation from full P&L / sensitive finance surfaces

---

## Explicit non-goals for early phases

| Do not build in 5B–5C | Belongs in |
|------------------------|------------|
| Inventory weekday assignment / purchasing | 5D / 5F |
| Mobile Revenue & Cost entry | 5E |
| Chat, work orders, exception platforms | Never (per earlier product direction) |
| Mixing new work into Phase 5A commit | Never |

---

## Next approval gate

1. Push Phase 5A when approved.  
2. Start **Phase 5B** only after explicit approval.  
3. **Phase 5C** (this Requirement 1) before treating Role as a hard productivity dimension.  
4. **Phase 5E** (this Requirement 2) after 5B–5D as sequenced above (or as reordered by product).
