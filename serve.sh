#!/usr/bin/env bash
# Build the site and serve it at http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
python3 build.py
echo "  http://localhost:8000"
exec python3 -m http.server 8000 --directory _site
