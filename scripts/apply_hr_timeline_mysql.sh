#!/usr/bin/env bash
# Apply backend/sql/hr_timeline_v1.sql
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/apply_sql_mysql_connector.py" "$ROOT/backend/sql/hr_timeline_v1.sql"
