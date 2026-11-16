@echo off
rem Double-cliquez ici (ou lancez "lancer-local.cmd -Ia" pour la vraie IA) : lance lancer-local.ps1 sans changer la politique d execution de Windows.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lancer-local.ps1" %*
pause
