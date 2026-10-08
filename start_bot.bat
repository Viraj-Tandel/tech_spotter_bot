@echo off
title Tech Spotter Telegram Bot
echo ========================================================
echo Starting Tech Spotter Bot (Digital Body Double)...
echo ========================================================
echo.

set PYTHON_EXE=C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe

if not exist "%PYTHON_EXE%" (
    echo Python 3.11 was not found at standard path. Trying system python...
    python bot.py
) else (
    "%PYTHON_EXE%" bot.py
)

pause
