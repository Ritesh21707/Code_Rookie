@echo off
cd /d "%~dp0"
where code >nul 2>nul
if %errorlevel%==0 (
  code .
) else (
  echo VS Code command "code" was not found.
  echo Open VS Code manually and choose File ^> Open Folder, then select:
  echo %cd%
  pause
)
