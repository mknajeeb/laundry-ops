#!/usr/bin/env bash
# Apply backend/sql/ta_washpro_bridge.sql to Azure MySQL (creates ta_users + permission seeds).
#
# Default: mysql-connector-python (avoids mysql CLI 9+ / ERROR 2059 mysql_native_password plugin).
# USE_MYSQL_CLI=1 to force the mysql binary.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SQL_FILE="$ROOT/backend/sql/ta_washpro_bridge.sql"

if [[ ! -f "$SQL_FILE" ]]; then
  echo "Missing: $SQL_FILE"
  exit 1
fi

if [[ "${USE_MYSQL_CLI:-}" == "1" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$ROOT/.env"
    set +a
  fi
  MYSQL_HOST="${MYSQL_HOST:-${DB_HOST:-}}"
  MYSQL_USER="${MYSQL_USER:-${DB_USER:-}}"
  MYSQL_PASSWORD="${MYSQL_PASSWORD:-${DB_PASSWORD:-}}"
  MYSQL_DATABASE="${MYSQL_DATABASE:-${DB_NAME:-}}"
  MYSQL_PORT="${MYSQL_PORT:-${DB_PORT:-3306}}"
  : "${MYSQL_HOST:?Set MYSQL_HOST or DB_HOST in .env}"
  : "${MYSQL_USER:?Set MYSQL_USER or DB_USER in .env}"
  : "${MYSQL_PASSWORD:?Set MYSQL_PASSWORD or DB_PASSWORD in .env}"
  : "${MYSQL_DATABASE:?Set MYSQL_DATABASE or DB_NAME in .env}"
  echo "Applying (mysql CLI) $SQL_FILE → ${MYSQL_USER}@${MYSQL_HOST}:${MYSQL_PORT}/${MYSQL_DATABASE}"
  echo "(You can also paste the same file into MySQL Workbench and run it there.)"
  args=(mysql)
  if [[ "${MYSQL_SSL_REQUIRED:-}" == "1" ]] || [[ "${MYSQL_SSL_REQUIRED:-}" == "true" ]]; then
    args+=(--ssl-mode=REQUIRED)
  fi
  if [[ -n "${MYSQL_SSL_CA:-}" ]]; then
    args+=(--ssl-ca="$MYSQL_SSL_CA")
  fi
  args+=(-h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE")
  "${args[@]}" < "$SQL_FILE"
  echo "Done. If other TA tables are missing (geofences, shift_sessions, …), plan a full TA schema with your DBA—see backend/schema_ta.sql (do not run DROP statements on production blindly)."
  exit 0
fi

python3 "$ROOT/scripts/apply_sql_mysql_connector.py" "$SQL_FILE"
echo "Done. If other TA tables are missing (geofences, shift_sessions, …), plan a full TA schema with your DBA—see backend/schema_ta.sql (do not run DROP statements on production blindly)."
