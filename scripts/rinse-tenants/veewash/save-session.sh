#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")/.." && pwd)/_tenant-env.sh" "${BASH_SOURCE[0]}"
echo "VEEWASH — log in with your VEEWASH Rinse vendor account, then press Enter in this terminal."
exec node save-session.mjs
