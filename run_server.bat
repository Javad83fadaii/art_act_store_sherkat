@echo off
cd /d "%~dp0"

call .venv\Scripts\activate

echo ASGI Server (Daphne) is running on port 8080...
echo Do NOT close this window!

python -m daphne -b 127.0.0.1 -p 8080 config.asgi:application

pause
