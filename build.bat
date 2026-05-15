@echo off
chcp 65001 >nul
title GameInSteam — Build

echo.
echo ╔══════════════════════════════════════════╗
echo ║        GameInSteam — EXE Builder         ║
echo ╚══════════════════════════════════════════╝
echo.

:: ── 0. Versiyon ──────────────────────────────────────────────────────────
echo [1/4]  Reading version...
if not exist "VERSION.txt" echo 5.0 > VERSION.txt
for /f "usebackq delims=" %%i in ("VERSION.txt") do set VERSION=%%i
for /f "tokens=* delims= " %%x in ("%VERSION%") do set VERSION=%%x
echo       Version: %VERSION%

:: installer.iss içindeki versiyon satırını güncelle
powershell -NoProfile -ExecutionPolicy Bypass -Command "$f = Get-Content 'installer.iss' -Raw; $f = $f -replace '#define MyAppVersion\s+\"\"[^\"\"]*\"\"', '#define MyAppVersion \"'%VERSION%'\"'; [IO.File]::WriteAllText('installer.iss', $f)"

:: ── 1. Python DLL yolu ───────────────────────────────────────────────────
echo.
echo [2/4]  Locating Python runtime...
for /f "usebackq delims=" %%i in (
  `python -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'python%PYTHON_VERSION_NODOT%.dll'))" 2^>nul`
) do set PYTHON_DLL=%%i

set PYTHON_DLL_ARG=
if exist "%PYTHON_DLL%" (
  echo       Found: %PYTHON_DLL%
  set "PYTHON_DLL_ARG=--add-binary \"%PYTHON_DLL%;.\""
) else (
  echo       DLL not found — PyInstaller will handle it automatically.
)

:: ── 2. PyInstaller ───────────────────────────────────────────────────────
echo.
echo [3/4]  Building EXE with PyInstaller...
echo       (This may take 1-3 minutes)
echo.

pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "GameInSteam" ^
    --icon "logo.ico" ^
    --add-data "steam_handler.py;." ^
    --add-data "ui.py;." ^
    --add-data "updater.py;." ^
    --add-data "VERSION.txt;." ^
    --add-data "logo.ico;." ^
    --add-data "logo.png;." ^
    --add-data "xinput1_4.dll;." ^
    %PYTHON_DLL_ARG% ^
    --hidden-import=requests ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageDraw ^
    --hidden-import=PIL.ImageTk ^
    --hidden-import=certifi ^
    --hidden-import=urllib3 ^
    --hidden-import=charset_normalizer ^
    --hidden-import=winreg ^
    --hidden-import=zipfile ^
    --hidden-import=tempfile ^
    --hidden-import=json ^
    --hidden-import=tkinter ^
    --hidden-import=tkinter.ttk ^
    --hidden-import=tkinter.messagebox ^
    --hidden-import=customtkinter ^
    --hidden-import=threading ^
    --hidden-import=subprocess ^
    --collect-all certifi ^
    --collect-all charset_normalizer ^
    --collect-all PIL ^
    --collect-all customtkinter ^
    --collect-submodules=ctypes ^
    --collect-submodules=encodings ^
    --noupx ^
    --clean ^
    main.py

if %ERRORLEVEL% NEQ 0 (
  echo.
  echo  ╔═══════════════════════════════╗
  echo  ║   PyInstaller BUILD FAILED!   ║
  echo  ╚═══════════════════════════════╝
  pause
  exit /b 1
)

echo.
echo       ✅ EXE built: dist\GameInSteam.exe
echo.

:: ── 3. Inno Setup ────────────────────────────────────────────────────────
echo [4/4]  Building installer with Inno Setup...
echo.

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe"       set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo  ⚠️  Inno Setup 6 not found!
  echo     Download from: https://jrsoftware.org/isdl.php
  echo     Then re-run this build.
  echo.
  echo     EXE is available at: dist\GameInSteam.exe
  goto :done
)

if not exist "Output" mkdir Output

"%ISCC%" installer.iss

if %ERRORLEVEL% NEQ 0 (
  echo.
  echo  ╔═══════════════════════════════╗
  echo  ║   Inno Setup BUILD FAILED!    ║
  echo  ╚═══════════════════════════════╝
  pause
  exit /b 1
)

echo.
echo       ✅ Installer: Output\GameInSteam_Setup_v%VERSION%.exe

:: ── 4. Temizlik ──────────────────────────────────────────────────────────
echo.
echo       Cleaning up build artifacts...
if exist "build"             rmdir /s /q "build"             >nul 2>&1
if exist "GameInSteam.spec"  del   /f     "GameInSteam.spec" >nul 2>&1

:done
echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║                    BUILD COMPLETE!                       ║
echo ║                                                          ║
echo ║   EXE:       dist\GameInSteam.exe                       ║
echo ║   Installer: Output\GameInSteam_Setup_v%VERSION%.exe        ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
pause
