@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0apps\artwork-review\start.ps1"
if errorlevel 1 pause
