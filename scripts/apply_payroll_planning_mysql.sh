#!/usr/bin/env bash
# Apply Payroll Planning Layer DDL to MySQL (staging/test only).
#
# Order:
#   1) payroll_schedule_v1.sql
#   2) payroll_schedule_v2.sql
#   3) payroll_roster_share_v1.sql
#   4) payroll_calendar_settings_v1.sql
#
# Safety: set PAYROLL_PLANNING_ALLOW_MIGRATE=1 in the environment, or use a database
# whose name contains "staging" or "test" (case-insensitive).
#
# Usage:
#   PAYROLL_PLANNING_ALLOW_MIGRATE=1 ./scripts/apply_payroll_planning_mysql.sh
#   # or paste each file into MySQL Workbench against your staging server
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.env"
  set +a
fi

MYSQL_DATABASE="${MYSQL_DATABASE:-${DB_NAME:-}}"
db_lc="$(echo "$MYSQL_DATABASE" | tr '[:upper:]' '[:lower:]')"
if [[ "${PAYROLL_PLANNING_ALLOW_MIGRATE:-}" != "1" ]]; then
  if [[ "$db_lc" != *staging* && "$db_lc" != *test* ]]; then
    echo "Refusing to migrate database '${MYSQL_DATABASE}'."
    echo "Payroll planning migrations are staging/test only."
    echo "Set PAYROLL_PLANNING_ALLOW_MIGRATE=1 only when you intend this database."
    exit 1
  fi
fi

SQL_FILES=(
  "$ROOT/backend/sql/payroll_schedule_v1.sql"
  "$ROOT/backend/sql/payroll_schedule_v2.sql"
  "$ROOT/backend/sql/payroll_roster_share_v1.sql"
  "$ROOT/backend/sql/payroll_calendar_settings_v1.sql"
)

for f in "${SQL_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "Missing: $f"
    exit 1
  fi
done

echo "Target: ${MYSQL_USER:-?}@${MYSQL_HOST:-?}/${MYSQL_DATABASE}"
echo "Applying ${#SQL_FILES[@]} payroll planning migration files…"
for f in "${SQL_FILES[@]}"; do
  echo "  → $(basename "$f")"
  python3 "$ROOT/scripts/apply_sql_mysql_connector.py" "$f"
done
echo "Done. Verify tables: payroll_schedule_entries, payroll_roster_share_links, payroll_calendar_settings."
