#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Default port
PORT="${1:-8000}"

if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

export PATH="$HOME/.local/bin:$PATH"

echo "Starting MCP RAG Server on port $PORT..."
echo "Endpoint: http://0.0.0.0:$PORT/mcp"
echo "Press Ctrl+C to stop"
echo ""

if [ "$PORT" -lt 1024 ]; then
    echo "(Port $PORT requires sudo)"
    sudo SERVER_PORT="$PORT" .venv/bin/python -u main.py
else
    SERVER_PORT="$PORT" .venv/bin/python -u main.py
fi
