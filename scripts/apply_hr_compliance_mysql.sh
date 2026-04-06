#!/usr/bin/env bash
# Apply backend/sql/hr_compliance_v1.sql using MYSQL_* from .env (same pattern as apply_ta_bridge_mysql.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ ! -f .env ]]; then
  echo "Missing .env in $ROOT"
  exit 1
fi
set -a
# shellcheck disable=SC1091
source .env
set +a
SQL_FILE="${ROOT}/backend/sql/hr_compliance_v1.sql"
echo "Applying ${SQL_FILE} to ${MYSQL_HOST:-localhost}/${MYSQL_DATABASE:-laundryapp} ..."
mysql -h "${MYSQL_HOST:-127.0.0.1}" -P "${MYSQL_PORT:-3306}" -u "${MYSQL_USER:-root}" -p"${MYSQL_PASSWORD:-}" "${MYSQL_DATABASE:-laundryapp}" < "${SQL_FILE}"
echo "Done."
