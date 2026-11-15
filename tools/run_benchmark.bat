@echo off
rem GLASS CITY benchmark. Set GODOT to your Godot 4.3 executable if it is not on PATH.
rem Writes benchmark.json into the Godot user folder (%%APPDATA%%\Godot\app_userdata\GLASS CITY\) and prints a summary.
if "%GODOT%"=="" set GODOT=godot
cd /d "%~dp0\.."
"%GODOT%" --path . --resolution 1920x1080 -- --benchmark=user://benchmark.json
echo.
echo Results: %APPDATA%\Godot\app_userdata\GLASS CITY\benchmark.json
pause
