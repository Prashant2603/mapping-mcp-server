#!/usr/bin/env bash
set -e

echo "=================================="
echo " MCP RAG Server - Setup (Linux/WSL)"
echo "=================================="

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }

# 1. Check for uv
echo ""
echo "Checking prerequisites..."

if command -v uv &>/dev/null; then
    ok "uv is installed ($(uv --version))"
else
    warn "uv not found. Installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        ok "uv installed successfully"
    else
        fail "Failed to install uv"
        exit 1
    fi
fi

# 2. Create venv with Python 3.12
echo ""
if [ -d ".venv" ] && [ -f ".venv/bin/python" ]; then
    PY_VER=$(.venv/bin/python --version 2>&1)
    ok "Virtual environment exists ($PY_VER)"
else
    warn "Creating virtual environment with Python 3.12..."
    uv venv --python 3.12 .venv
    ok "Virtual environment created"
fi

# 3. Install dependencies
echo ""
echo "Installing dependencies..."
source .venv/bin/activate
uv pip install -r requirements.txt
ok "Dependencies installed"

# 4. Create data directories
echo ""
mkdir -p data/formats data/mapping_sets data/functions_docs
ok "Data directories ready"

# 5. Verify
echo ""
echo "Verifying installation..."
.venv/bin/python -c "
import mcp; print(f'  mcp: {mcp.__version__}')
import chromadb; print(f'  chromadb: {chromadb.__version__}')
import pydantic; print(f'  pydantic: {pydantic.__version__}')
print('  All imports OK')
"
ok "Setup complete!"

echo ""
echo "=================================="
echo " Next steps:"
echo "  1. Place your data files in data/formats/, data/mapping_sets/, data/functions_docs/"
echo "  2. Run the server: ./run.sh 8000 --reindex       (first time, indexes all files)"
echo "     Subsequent runs: ./run.sh 8000 --no-reindex   (skip indexing, fast startup)"
echo "  3. Run tests: source .venv/bin/activate && pytest tests/ -v"
echo "=================================="
