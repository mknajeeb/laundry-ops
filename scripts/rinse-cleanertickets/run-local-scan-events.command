#!/bin/bash
# macOS: double-click — pick WashPro or VeeWash, export scan-events CSVs.
cd "$(dirname "$0")"
exec bash ./run-local-scan-events.sh "$@"
