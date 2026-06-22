# VeeWash / WashPro — HR Architecture (Locked)

**Status:** Approved for implementation.

---

## Three-layer model

| Layer | Document / system | Contents | Re-signature |
|---|---|---|---|
| **Policies** | Employee Handbook · Contractor Service Standards Guide | Communications, discipline framework, conduct, safety | Rarely |
| **Performance expectations** | Performance Standards Addendum (signed) | Qualitative standards + **attendance policies** — **no fixed numeric targets** | When addendum text materially changes |
| **Numeric targets** | Performance Settings · `rinse_folding_settings` · benchmark dashboards | Bags/hr, lbs/hr, quality %, processing times | **Never** — editable in settings only |

Workers acknowledge in the addendum that management may establish, revise, and communicate operational targets without a new signed document.

---

## Signed worker documents

| Employee | Contractor |
|---|---|
| Employee Handbook (+ signature page) | Independent Contractor Agreement |
| Performance Standards Addendum (+ signature page) | Contractor Service Standards Guide (+ signature page) |
| | Performance Standards Addendum (+ signature page) |

**No** coaching, warning, acknowledgement, or separation forms. **No** worker signatures on discipline steps.

---

## Discipline & communication

Delivered by **email** (8 templates in `email_templates.md`) + **HR Timeline** entry (manager-only).

### Attendance / tardiness flow (locked)

| Step | Action |
|---|---|
| First late arrival | Coaching email + HR Timeline (Coaching) |
| Second late arrival | Warning email + HR Timeline (Warning) |
| Continued tardiness / pattern | Separation at management discretion |
| No-call / no-show | Immediate separation possible — no warning required |

### Other flows

| Issue type | Flow |
|---|---|
| Pattern attendance issues | Warning → continued issue → Separation |
| Performance issues | Warning → continued issue → Separation |
| Customer item care / quality | Warning → continued issue → Separation (direct separation if severity warrants) |
| Serious incidents | Immediate separation possible — full management discretion |

---

## HR Timeline

**Entry types:** Coaching · Warning · Attendance Issue · Performance Issue · Safety Issue · Customer Complaint · Recognition · Separation Note · **Management Note**

**Management Note:** Internal observations that are **not** formal coaching or warning.

**Fields:** Date · Category · Description · Manager · Optional attachment · **No signatures**

**Implementation:** `hr_timeline_entries` table · People workspace **HR Timeline** tab · discipline email dialog creates timeline entry automatically.

---

## Review / draft files

| File | Role |
|---|---|
| `employee_handbook_OUTLINE.md` | Handbook structure |
| `contractor_service_standards_guide_OUTLINE.md` | Guide structure |
| `performance_standards_addendum_OUTLINE.md` | Addendum structure (no numeric targets) |
| `email_templates.md` | 8 email templates |
| `employee_performance_standards_addendum.md` | Draft addendum (qualitative + attendance) |
| `contractor_performance_standards_addendum.md` | Draft addendum (qualitative + attendance) |

**Re-sign addendum only** when written expectation/policy text in the addendum materially changes — not when benchmarks change in Performance Settings.
