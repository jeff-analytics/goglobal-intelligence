@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
title BorderMargin Repair

echo This will remove the local Python virtual environment and reinstall it.
echo Your project source files and .env are kept.
echo.
if exist "backend\.venv" rmdir /s /q "backend\.venv"
echo Old Python environment removed.
echo Starting clean installation...
call "%ROOT%\run_win.bat"
