; =============================================
; GameInSteam - Inno Setup Installer Script
; =============================================
; Inno Setup 6+ gerektirir: https://jrsoftware.org/isdl.php
; Derleme: ISCC.exe installer.iss  veya  build.bat

#define MyAppName "GameInSteam"
#define MyAppVersion "2.5"
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

; Güzel görünüm
WizardSizePercent=110

; Lisans (opsiyonel)
; LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"
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
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*"

[Code]
// Kurulum sırasında kontroller
function InitializeSetup(): Boolean;
var
  SteamDir: String;
begin
  Result := True;

  // Eski versiyon kontrolü
  if RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}_is1') then
  begin
    if MsgBox('GameInSteam is already installed. Do you want to update it?',
              mbConfirmation, MB_YESNO) = IDNO then
    begin
      Result := False;
      Exit;
    end;
  end;

  // Steam kurulu mu kontrol et
  SteamDir := ExpandConstant('{commonpf32}\Steam');
  if not DirExists(SteamDir) then
  begin
    MsgBox('Steam is not installed at the default location:' + #13#10 +
           SteamDir + #13#10#13#10 +
           'Please install Steam first, then run this installer again.',
           mbError, MB_OK);
    Result := False;
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
             '• GameInSteam has been installed.' + #13#10 +
             '• xinput1_4.dll has been placed in your Steam directory.' + #13#10#13#10 +
             'Please restart Steam before using GameInSteam.',
             mbInformation, MB_OK);
    end;
  end;
end;

