#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# AgentGRIT 2.0 - Start Script
# ═══════════════════════════════════════════════════════════════════════════════

cd "$(dirname "$0")"

# Activate virtual environment
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "Virtual environment not found. Run scripts/setup-mac.sh first."
    exit 1
fi

# Pass all arguments to main
python -m src.main "$@"
