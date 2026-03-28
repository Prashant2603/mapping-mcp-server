@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found. Run setup.bat first.
    exit /b 1
)

set PORT=%1
if "%PORT%"=="" set PORT=8000

set INDEX_FLAG=%2
if "%INDEX_FLAG%"=="" (
    echo Usage: run.bat [PORT] ^<--reindex^|--no-reindex^|--full-reindex^>
    echo.
    echo   --reindex        Incremental: only index new/changed files
    echo   --no-reindex     Skip indexing, use existing vector store
    echo   --full-reindex   Wipe vector store and rebuild from scratch
    exit /b 1
)

echo Starting MCP RAG Server on port %PORT% (%INDEX_FLAG%)...
echo Endpoint: http://0.0.0.0:%PORT%/mcp
echo Press Ctrl+C to stop
echo.

set SERVER_PORT=%PORT%
.venv\Scripts\python -u main.py %INDEX_FLAG%

endlocal
