@echo off
REM Start from this script's directory so app.py and backend/.env resolve correctly.
cd /d "%~dp0backend"
conda run -n paper2ppt uvicorn app:app --reload --host 0.0.0.0 --port 8000
