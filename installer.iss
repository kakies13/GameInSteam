; =============================================
; GameInSteam - Inno Setup Installer Script
; =============================================
; Inno Setup 6+ gerektirir: https://jrsoftware.org/isdl.php
; Derleme: ISCC.exe installer.iss  veya  build.bat

#define MyAppName "GameInSteam"
#define MyAppVersion "2.8"
#define MyAppPublisher "GameInSteam"
#define MyAppURL "https://gameinsteam.com"
#define MyAppExeName "GameInSteam.exe"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=GameInSteam_Setup_v{#MyAppVersion}
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

; Güzel görünüm
WizardSizePercent=110

; Son kullanıcı için otomatik kurulum
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no
DisableFinishedPage=no

; Lisans (opsiyonel)
; LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "installdll"; Description: "Install xinput1_4.dll to Steam directory (required)"; Flags: checkedonce

[Files]
; Ana EXE dosyası (PyInstaller çıktısı)
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; xinput1_4.dll — Proxy DLL, Steam dizinine kopyalanır
Source: "xinput1_4.dll"; DestDir: "{commonpf32}\Steam"; Tasks: installdll; Flags: ignoreversion uninsneveruninstall

; README
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Visual C++ Redistributables otomatik indirme ve kurulumu (eğer eksikse)
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -Command ""try { $url = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'; $output = '{tmp}\vc_redist.x64.exe'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri $url -OutFile $output -UseBasicParsing -ErrorAction Stop; Start-Process -FilePath $output -ArgumentList '/quiet', '/norestart' -Wait -NoNewWindow; Remove-Item $output -Force -ErrorAction SilentlyContinue; exit 0 } catch { exit 1 }"""; StatusMsg: "Installing Visual C++ Redistributables..."; Check: VCRedistNeedsInstall; Flags: runhidden waituntilterminated

; Ana uygulama
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*"

[Code]
// Visual C++ Redistributables kontrolü
function IsVCRedistInstalled(): Boolean;
var
  Version: String;
begin
  Result := False;
  // Visual C++ 2015-2022 Redistributables kontrolü
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) then
  begin
    Result := True;
    Exit;
  end;
  // Alternatif kontrol
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) then
  begin
    Result := True;
    Exit;
  end;
  // 2015-2022 Redistributables kontrolü
  if RegKeyExists(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64') then
  begin
    Result := True;
    Exit;
  end;
end;

// VC++ Redistributables kurulumu gerekli mi?
function VCRedistNeedsInstall(): Boolean;
begin
  Result := not IsVCRedistInstalled();
end;

// Kurulum sırasında kontroller
function InitializeSetup(): Boolean;
var
  SteamDir: String;
begin
  Result := True;

  // Eski versiyon kontrolü
  if RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1') then
  begin
    if MsgBox('GameInSteam is already installed. Do you want to update it?' + #13#10#13#10 +
              'Click Yes to update, or No to cancel.',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;

  // Steam kurulu mu kontrol et (uyarı ver ama kuruluma devam et)
  SteamDir := ExpandConstant('{commonpf32}\Steam');
  if not DirExists(SteamDir) then
  begin
    if MsgBox('Steam is not installed at the default location:' + #13#10 +
              SteamDir + #13#10#13#10 +
              'GameInSteam requires Steam to be installed.' + #13#10 +
              'Do you want to continue with the installation anyway?' + #13#10 +
              '(You can install Steam later and run GameInSteam)',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;
end;

// Kurulum sonrası bilgilendirme
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('installdll') then
    begin
      MsgBox('✅ Installation complete!' + #13#10#13#10 +
             '• GameInSteam has been installed successfully.' + #13#10 +
             '• Visual C++ Redistributables has been installed automatically (if needed).' + #13#10 +
             '• xinput1_4.dll has been placed in your Steam directory.' + #13#10#13#10 +
             '⚠️ IMPORTANT: Please restart Steam before using GameInSteam!' + #13#10#13#10 +
             'After restarting Steam, you can start adding games to your library.',
             mbInformation, MB_OK);
    end else
    begin
      MsgBox('✅ Installation complete!' + #13#10#13#10 +
             '• GameInSteam has been installed successfully.' + #13#10 +
             '• Visual C++ Redistributables has been installed automatically (if needed).' + #13#10#13#10 +
             '⚠️ IMPORTANT: Please restart Steam before using GameInSteam!' + #13#10#13#10 +
             'After restarting Steam, you can start adding games to your library.',
             mbInformation, MB_OK);
    end;
  end;
end;

