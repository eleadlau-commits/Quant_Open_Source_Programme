@echo off
rem Windows: double-click to open Strategy Lab.
rem The first run sets up a private Python environment in .venv (takes a few minutes).
cd /d "%~dp0"
if not exist "pyproject.toml" (
  echo This launcher must stay inside the Strategy Lab folder.
  echo If you opened it from inside the ZIP: right-click the ZIP, choose "Extract All...",
  echo then open the extracted folder and double-click "Strategy Lab.bat" there.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo First run: setting up Strategy Lab ^(needs Python 3.11 or newer^)...
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if not exist ".venv\Scripts\python.exe" (
    echo Python 3 not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -e ".[desktop]"
  if errorlevel 1 (
    echo Setup failed, see the messages above.
    pause
    exit /b 1
  )
)
start "" ".venv\Scripts\pythonw.exe" -m honestbt.desktop
