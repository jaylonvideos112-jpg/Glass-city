@echo off
rem Run the in-game automated tests headless. Set GODOT to your Godot 4.3 executable if it is not on PATH.
if "%GODOT%"=="" set GODOT=godot
cd /d "%~dp0\.."
python tests\test_data.py
"%GODOT%" --headless --path . -- --test=res://tests/out/results.json
pause
