# Payroll UX — pre-deploy screenshot checklist

## Deploy commits (do not cherry-pick partially)

Payroll workflow UX and contractor payment records landed as **two commits** on the same branch. Both are required for correct payroll payout API behavior.

| Commit | Summary |
|--------|---------|
| `fc96584` | Redesign payroll manager workflow (payroll backend/frontend, tests, QA screenshots) |
| `af19558` | Enhance contractor payment records |

**Important:** `af19558` also contains shared `backend/ta_routes.py` updates needed by payroll payout route behavior, because contractor and payroll route changes were in the same file. Do not cherry-pick only `fc96584` and expect payroll payout routes to be fully current — include `af19558` (or an equivalent that contains the same `ta_routes.py` payroll payout changes, e.g. `approve_hours` and related payout routes).

Capture these after signing in as **manager** (ADMIN/OPS) and **accountant** (ACCOUNTANT role).

## Manager role

1. **Payroll dashboard** — `/payroll` (top summary card before tabs)
2. **Payout batch screen** — Payout Batches tab, batch selected, summary + worker table
3. **Payment & Details table** — Payment & Details tab, compact table view
4. **Expanded employee row** — expand one row on Payment & Details

## Accountant role

5. **Accountant payroll screen** — Accountant Payroll tab (single consolidated flow)

## Label QA (must NOT appear anywhere)

- sent to accountant
- accountant reviewed
- approved for payment
- closed (as payroll status)
- ready to send
- approved unpaid / Approved — unpaid

Allowed status labels only: **Draft**, **Ready For Payroll**, **Ready To Pay**, **Paid**.

## How to capture locally

```bash
# Terminal 1 — backend
cd /Users/kamisb./laundry_app && python3 run.py

# Terminal 2 — frontend
cd frontend && npm run dev
# Open http://127.0.0.1:5173/payroll
```

## Automated test results (local)

Run before deploy:

```bash
python3 -m pytest backend/tests/test_payroll_deploy_readiness.py \
  backend/tests/test_payroll_status_display.py \
  backend/tests/test_payroll_workflow.py \
  backend/tests/test_payout_details_paystub.py \
  backend/tests/test_accountant_role_access.py -q
```

**Latest run:** 73 passed.

**Live DB workflow smoke** (washpro org, temp batch, SQL cleanup after):

| Step | Result |
|------|--------|
| Draft → Approve Hours | `ready_for_payroll` |
| Save deductions | net $180.00 (gross $200 − FIT $20) |
| Finalize | `ready_to_pay` |
| Paystub HTML | generated (~52KB) |
| Mark Paid | `paid`, paid $200, outstanding $0 |

**Veewash existing batches:** internal `approved_for_payment` maps to UI **Ready For Payroll** (not finalized).

## Legacy accountant files (post-deploy cleanup)

Do **not** delete before this deploy. Confirmed unmounted:

- `AccountantReportsPanel.jsx`
- `AccountantPaymentQueuePanel.jsx`
- `AccountantW2PayrollPanel.jsx`

Not imported in `App.jsx` or `PayrollManagementPage.jsx`. Archive after deploy when convenient.

