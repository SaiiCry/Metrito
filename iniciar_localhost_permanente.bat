@echo off
cd /d "%~dp0"
title SIMMA - Servidor Localhost Permanente (http://127.0.0.1:8000)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0keep_alive_server.ps1"
