#!/usr/bin/env bash

# Ensure we're in the project root
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# Run the Python exporter
python3 scripts/export_codebase.py "$@"
