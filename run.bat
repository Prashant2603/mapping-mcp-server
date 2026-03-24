@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

set PORT=%1
if "%PORT%"=="" set PORT=8000

echo Starting MCP RAG Server on port %PORT%...
echo Endpoint: http://0.0.0.0:%PORT%/mcp
echo Press Ctrl+C to stop
echo.

set SERVER_PORT=%PORT%
.venv\Scripts\python -u main.py

endlocal
