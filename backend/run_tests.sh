#!/usr/bin/env bash
# Run the test suite — use this before deploying or pushing to GitHub.
#
# Usage:
#   cd backend
#   ./run_tests.sh
#
# Or directly:
#   cd backend
#   .venv/bin/pytest tests/ -v
set -e

cd "$(dirname "$0")"

echo "============================================================"
echo "Running NL-to-SQL Analytics Copilot test suite"
echo "============================================================"
echo ""

# Run pytest with verbose output
.venv/bin/pytest tests/ -v --tb=short

echo ""
echo "============================================================"
echo "Test run complete."
echo "============================================================"
