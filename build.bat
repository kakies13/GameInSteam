@echo off
title GameInSteam - Build
echo =============================================
echo    GameInSteam - EXE Builder
echo =============================================
echo.

:: 0. Versiyon numarasını oku ve artır
echo [0/4] Reading and incrementing version...
if not exist "VERSION.txt" (
    echo 4.0 > VERSION.txt
)
for /f "delims=" %%i in (VERSION.txt) do set CURRENT_VERSION=%%i
echo   Current version: %CURRENT_VERSION%

:: Versiyon numarasını parse et (major.minor)
for /f "tokens=1,2 delims=." %%a in ("%CURRENT_VERSION%") do (
    set MAJOR=%%a
    set MINOR=%%b
)

:: Minor versiyonu artır (Eger 4.5'e ulasmak istiyorsak bu adimi atlayabilir veya 4.5'e sabitleyebiliriz)
set NEW_VERSION=4.5
echo   Target version: %NEW_VERSION%

:: VERSION.txt'yi güncelle
echo %NEW_VERSION% > VERSION.txt
echo   ✅ Version updated to %NEW_VERSION%

:: installer.iss'deki versiyon numarasını güncelle
powershell -NoProfile -ExecutionPolicy Bypass -Command "$content = Get-Content installer.iss -Raw -Encoding UTF8; $content = $content -replace '(#define MyAppVersion \")[^\"]*(\")', \"`$1%NEW_VERSION%`$2\"; [System.IO.File]::WriteAllText('installer.iss', $content, [System.Text.Encoding]::UTF8)"
echo   ✅ installer.iss updated to %NEW_VERSION%

echo.

:: 1. Python DLL yolunu bul
echo [1/4] Finding Python DLL...
for /f "delims=" %%i in ('python -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), 'python314.dll'))"') do set PYTHON_DLL=%%i
if not exist "%PYTHON_DLL%" (
    echo [WARN] Python DLL not found at: %PYTHON_DLL%
    echo        Trying alternative paths...
    :: Alternatif yolları dene
    if exist "%PYTHON_DLL:~0,-20%python314.dll" (
        set PYTHON_DLL=%PYTHON_DLL:~0,-20%python314.dll
        echo        Found at alternative path: %PYTHON_DLL%
        set PYTHON_DLL_ARG=--add-binary "%PYTHON_DLL%;."
    ) else (
        echo        PyInstaller will try to find it automatically.
        set PYTHON_DLL_ARG=
    )
) else (
    echo        Found: %PYTHON_DLL%
    set PYTHON_DLL_ARG=--add-binary "%PYTHON_DLL%;."
)

:: 2. PyInstaller ile EXE oluştur
echo [2/4] Building EXE with PyInstaller...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "GameInSteam" ^
    --add-data "steam_handler.py;." ^
    --add-data "ui.py;." ^
    --add-data "updater.py;." ^
    --add-data "VERSION.txt;." ^
    %PYTHON_DLL_ARG% ^
    --hidden-import=requests ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageTk ^
    --hidden-import=selenium ^
    --hidden-import=selenium.webdriver ^
    --hidden-import=selenium.webdriver.chrome ^
    --hidden-import=selenium.webdriver.chrome.service ^
    --hidden-import=selenium.webdriver.chrome.options ^
    --hidden-import=selenium.webdriver.common.by ^
    --hidden-import=selenium.webdriver.support.ui ^
    --hidden-import=selenium.webdriver.support.expected_conditions ^
    --hidden-import=webdriver_manager ^
    --hidden-import=webdriver_manager.chrome ^
    --hidden-import=webdriver_manager.drivers.chrome ^
    --hidden-import=certifi ^
    --hidden-import=urllib3 ^
    --hidden-import=charset_normalizer ^
    --hidden-import=winreg ^
    --hidden-import=concurrent.futures ^
    --hidden-import=zipfile ^
    --hidden-import=json ^
    --hidden-import=vdf ^
    --hidden-import=tkinter ^
    --hidden-import=tkinter.ttk ^
    --hidden-import=tkinter.messagebox ^
    --hidden-import=tkinter.filedialog ^
    --hidden-import=customtkinter ^
    --hidden-import=threading ^
    --hidden-import=queue ^
    --hidden-import=subprocess ^
    --collect-all selenium ^
    --collect-all webdriver_manager ^
    --collect-all certifi ^
    --collect-all charset_normalizer ^
    --collect-all PIL ^
    --collect-submodules=ctypes ^
    --collect-submodules=encodings ^
    --collect-submodules=importlib ^
    --collect-binaries all ^
    --collect-all python ^
    --noupx ^
    --clean ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [3/4] Build complete!
echo   Output: dist\GameInSteam.exe
echo.

:: 3. Masaüstüne kopyala
echo [4/4] Copying to Desktop...
copy /Y "dist\GameInSteam.exe" "%USERPROFILE%\Desktop\GameInSteam.exe" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo   ✅ GameInSteam.exe masaustune kopyalandi!
) else (
    echo   [WARN] Desktop kopyalama basarisiz, dist klasorunden calistirabilirsin.
)

:: 3. Installer varsa derle
echo.
if exist "installer.iss" (
    echo Checking for Inno Setup...
    set "ISCC="
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
    if defined ISCC (
        echo Building installer with Inno Setup...
        "%ISCC%" installer.iss
        echo.
        echo   Installer: Output\GameInSteam_Setup_v%NEW_VERSION%.exe
    ) else (
        echo [INFO] Inno Setup bulunamadi - sadece EXE olusturuldu.
        echo        Installer icin: https://jrsoftware.org/isdl.php
    )
)

:: 4. Temizlik - build dosyalarını sil
echo.
echo Cleaning up build files...
if exist "build" rmdir /s /q "build" >nul 2>&1
if exist "GameInSteam.spec" del /f "GameInSteam.spec" >nul 2>&1
echo   Temizlik tamamlandi.

echo.
echo =============================================
echo   DONE!
echo   Masaustu: %USERPROFILE%\Desktop\GameInSteam.exe
echo   dist:     dist\GameInSteam.exe
echo =============================================
pause
