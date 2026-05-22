#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=../_tenant-env.sh
source "$(cd "$(dirname "$0")/.." && pwd)/_tenant-env.sh" "${BASH_SOURCE[0]}"
echo "WASHPRO — log in with your WASHPRO Rinse vendor account, then press Enter in this terminal."
exec node save-session.mjs
