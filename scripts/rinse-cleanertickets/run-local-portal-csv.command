#!/bin/bash
# macOS: double-click this file to open Terminal and run the scrape (not the .sh — that opens as text).
cd "$(dirname "$0")"
exec bash ./run-local-portal-csv.sh "$@"
