@echo off
title GameInSteam - Build
echo =============================================
echo    GameInSteam - EXE Builder
echo =============================================
echo.

:: 1. PyInstaller ile EXE oluştur
echo [1/3] Building EXE with PyInstaller...
pyinstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "GameInSteam" ^
    --add-data "steam_handler.py;." ^
    --add-data "ui.py;." ^
    --add-data "updater.py;." ^
    --hidden-import=requests ^
    --hidden-import=PIL ^
    --hidden-import=PIL.Image ^
    --hidden-import=PIL.ImageTk ^
    --hidden-import=selenium ^
    --hidden-import=webdriver_manager ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b 1
)

echo.
echo [2/3] Build complete!
echo   Output: dist\GameInSteam.exe
echo.

:: 2. Masaüstüne kopyala
echo [3/3] Copying to Desktop...
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
        echo   Installer: Output\GameInSteam_Setup_v2.5.exe
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
