#!/usr/bin/env bash
# ==============================================================================
# AI Security Monitor - Local On-Demand Command Center Runner
# 100% Free, Local-First, Zero-Cloud Architecture ($0/Month Law)
# Strict Arch Linux On-Demand Process Governance: Terminates cleanly on exit
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

PORT="${PORT:-8080}"
HOST="${HOST:-127.0.0.1}"

# Ensure data directory exists
mkdir -p "${PROJECT_ROOT}/data"

echo "=========================================================="
echo "  🌐 AI Security Monitor — Local Command Center"
echo "  Architecture: 100% Free, Local Silicon, Zero Cloud"
echo "  URL: http://${HOST}:${PORT}"
echo "=========================================================="

# Trap SIGINT/SIGTERM to ensure clean process termination (Arch On-Demand Law)
cleanup() {
    echo ""
    echo "🛑 Shutting down AI Security Monitor cleanly..."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Execute local command center via python module
exec python -m ai_security_monitor server --host "${HOST}" --port "${PORT}"
