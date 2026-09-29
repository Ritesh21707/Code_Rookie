@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -m unittest discover -s tests -v
) else (
  python -m unittest discover -s tests -v
)
pause
