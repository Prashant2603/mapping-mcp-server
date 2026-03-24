@echo off
setlocal enabledelayedexpansion

echo ==================================
echo  MCP RAG Server - Setup (Windows)
echo ==================================
echo.

:: 1. Check for Python
echo Checking prerequisites...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] Python not found. Checking for uv...
    goto :check_uv
)

for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
for /f "tokens=1,2 delims=." %%a in ("%PY_VER%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if %PY_MAJOR% geq 3 if %PY_MINOR% geq 10 (
    echo [OK] Python %PY_VER% found
    goto :setup_venv_python
)

echo [WARN] Python %PY_VER% is too old (need 3.10+). Will use uv to install Python 3.12.

:check_uv
where uv >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARN] uv not found. Installing...
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    if %errorlevel% neq 0 (
        echo [FAIL] Failed to install uv. Please install Python 3.10+ manually.
        exit /b 1
    )
    :: Refresh PATH
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
    echo [OK] uv installed
)

:: 2. Create venv with uv
echo.
if exist ".venv\Scripts\python.exe" (
    echo [OK] Virtual environment exists
) else (
    echo Creating virtual environment with Python 3.12...
    uv venv --python 3.12 .venv
    echo [OK] Virtual environment created
)
goto :install_deps

:setup_venv_python
echo.
if exist ".venv\Scripts\python.exe" (
    echo [OK] Virtual environment exists
) else (
    echo Creating virtual environment...
    python -m venv .venv
    echo [OK] Virtual environment created
)

:install_deps
:: 3. Install dependencies
echo.
echo Installing dependencies...
if exist "%USERPROFILE%\.local\bin\uv.exe" (
    uv pip install -r requirements.txt
) else (
    where uv >nul 2>&1
    if %errorlevel% equ 0 (
        uv pip install -r requirements.txt
    ) else (
        .venv\Scripts\pip install -r requirements.txt
    )
)
echo [OK] Dependencies installed

:: 4. Create data directories
echo.
if not exist "data\formats" mkdir data\formats
if not exist "data\mapping_sets" mkdir data\mapping_sets
if not exist "data\functions_docs" mkdir data\functions_docs
echo [OK] Data directories ready

:: 5. Verify
echo.
echo Verifying installation...
.venv\Scripts\python -c "import mcp; print(f'  mcp: {mcp.__version__}'); import chromadb; print(f'  chromadb: {chromadb.__version__}'); import pydantic; print(f'  pydantic: {pydantic.__version__}'); print('  All imports OK')"
echo [OK] Setup complete!

echo.
echo ==================================
echo  Next steps:
echo   1. Place your data files in data\formats\, data\mapping_sets\, data\functions_docs\
echo   2. Run the server: run.bat
echo   3. Run tests: .venv\Scripts\activate ^& pytest tests\ -v
echo ==================================

endlocal
