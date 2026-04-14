#!/usr/bin/env bash
# Deploy application code: commit + push to main → GitHub Actions deploys API + Static Web App.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== Status =="
git status -sb

echo ""
echo "== Run these (edit commit message) =="
echo "  git add backend frontend scripts .github"
echo "  git commit -m \"Deploy: Washpro + payroll integration\""
echo "  git push origin main"
echo ""
echo "Then open GitHub → Actions and wait for:"
echo "  - laundryops-api (Azure Web App)"
echo "  - Azure Static Web Apps workflow (frontend)"
echo ""
echo "Database is NOT updated by git push. After deploy, run SQL migrations as needed:"
echo "  scripts/apply_ta_bridge_mysql.sh"
echo "  scripts/apply_hr_compliance_mysql.sh   # HR extended profiles + document tables"
echo ""
echo "Rinse async import: table rinse_import_jobs is created on first use (see docs/AZURE_RINSE_DEPLOY.md)."
