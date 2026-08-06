#!/usr/bin/env bash
# Activates the venv (creating it via setup.sh if missing) and runs main.py
set -e

if [ ! -d "venv" ]; then
    echo "[INFO] venv not found, running setup.sh first..."
    bash setup.sh
fi

# shellcheck disable=SC1091
source venv/bin/activate
python main.py
