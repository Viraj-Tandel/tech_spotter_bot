@echo off
title Stop Tech Spotter Bot
echo Stopping any running Tech Spotter Bot processes...
wmic process where "CommandLine like '%%bot.py%%' and Name='python.exe'" call terminate >nul 2>&1
echo Done.
timeout /t 2 >nul
