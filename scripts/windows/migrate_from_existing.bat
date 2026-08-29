@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ROOT=%%~fI"
cd /d "%ROOT%"
title BorderMargin V5.3.x -> V5.3.8 Data Migration

echo ================================================
echo   BorderMargin V5.3.x -> V5.3.8 Data Migration
echo ================================================
echo.
set /p OLD_DIR=Enter the existing BorderMargin V5.3.x folder path: 
if not defined OLD_DIR exit /b 1
set "OLD_DIR=%OLD_DIR:"=%"
if not exist "%OLD_DIR%" (
  echo [ERROR] Folder not found.
  pause
  exit /b 1
)

if exist "%OLD_DIR%\.env" copy /Y "%OLD_DIR%\.env" ".env" >nul
if exist "%OLD_DIR%\backend\.env" if not exist ".env" copy /Y "%OLD_DIR%\backend\.env" ".env" >nul
if not exist "backend\data" mkdir "backend\data"
if exist "%OLD_DIR%\backend\data\bordermargin.db" copy /Y "%OLD_DIR%\backend\data\bordermargin.db" "backend\data\bordermargin.db" >nul
if exist "%OLD_DIR%\backend\bordermargin.db" copy /Y "%OLD_DIR%\backend\bordermargin.db" "backend\data\bordermargin.db" >nul
if exist "%OLD_DIR%\bordermargin.db" copy /Y "%OLD_DIR%\bordermargin.db" "backend\data\bordermargin.db" >nul
if exist "%OLD_DIR%\backend\data\ebay_taxonomy" xcopy /E /I /Y "%OLD_DIR%\backend\data\ebay_taxonomy" "backend\data\ebay_taxonomy" >nul
if exist "%OLD_DIR%\backend\data\hs_reference.json" copy /Y "%OLD_DIR%\backend\data\hs_reference.json" "backend\data\hs_reference.json" >nul

echo.
echo [DONE] Local settings, database and taxonomy cache were copied.
echo [DONE] Run run_win.bat.
pause
