#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup.sh
# Automated environment setup for Linux / macOS.
# Creates a Python virtual environment and installs all dependencies.
# Run this ONCE (or whenever requirements.txt changes).
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
# ---------------------------------------------------------------------------
set -e

echo "=================================================="
echo " AWS Identity Center Inactive User Report - Setup "
echo "=================================================="

PYTHON_BIN=""
for cmd in python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PYTHON_BIN="$cmd"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "[ERROR] Python 3 was not found on PATH."
    echo "        Install Python 3.9+ first:"
    echo "          Debian/Ubuntu : sudo apt-get install -y python3 python3-venv python3-pip"
    echo "          RHEL/Amazon Linux : sudo yum install -y python3 python3-pip"
    echo "          macOS (brew)  : brew install python3"
    exit 1
fi

echo "[INFO] Using $($PYTHON_BIN --version)"

VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "[INFO] Creating virtual environment in ./$VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
else
    echo "[INFO] Virtual environment already exists, skipping creation."
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[INFO] Upgrading pip"
pip install --upgrade pip >/dev/null

echo "[INFO] Installing dependencies from requirements.txt"
pip install -r requirements.txt

mkdir -p output

echo ""
echo "[SUCCESS] Setup complete."
echo ""
echo "Next steps:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "(Or just run ./run.sh which does both steps for you.)"
