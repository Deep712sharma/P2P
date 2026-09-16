@echo off
REM Start from this script's directory when launched by double-click or a shell.
cd /d "%~dp0frontend"
conda run -n paper2ppt npm run dev
