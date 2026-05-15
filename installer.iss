; ============================================================
;  GameInSteam — Inno Setup 6 Installer Script
; ============================================================

#define MyAppName     "GameInSteam"
#define MyAppVersion  "5.0"
#define MyAppPublisher "kakies13"
#define MyAppURL      "https://github.com/kakies13/GameInSteam"
#define MyAppExeName  "GameInSteam.exe"

[Setup]
AppId={{8F4A2B1C-3D5E-4F6A-9B8C-7D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableDirPage=no
DisableProgramGroupPage=yes
LicenseFile=LICENSE
OutputDir=Output
OutputBaseFilename=GameInSteam_Setup_v{#MyAppVersion}
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
CloseApplicationsFilter=*{#MyAppExeName}
AllowNoIcons=yes
VersionInfoVersion={#MyAppVersion}.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to [name] Setup
WelcomeLabel2=This will install [name/ver] on your computer.%n%nGameInSteam lets you add any game to your Steam library in seconds — directly from the gamelist repo, no Chrome required.%n%nClick Next to continue.
FinishedLabel=Setup has finished installing [name] on your computer.%n%nSteam plugin (xinput1_4.dll) was configured automatically if Steam is installed.%n%nClick Finish to launch or close Setup.
FinishedHeadingLabel=Completing [name] Setup

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Additional icons:"
Name: "autostart"; Description: "Launch {#MyAppName} when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "VERSION.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "xinput1_4.dll"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}"; Permissions: users-full

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: startmenuicon
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"; IconFilename: "{app}\logo.ico"; Tasks: startmenuicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "SOFTWARE\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKLM; Subkey: "SOFTWARE\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "SOFTWARE\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; Flags: nowait postinstall skipifsilent shellexec; WorkingDir: "{app}"

[UninstallRun]
Filename: "taskkill"; Parameters: "/F /IM {#MyAppExeName}"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\.gameinsteam_session.json"
Type: dirifempty; Name: "{app}"

[Code]
const
  MIN_XINPUT_DLL_SIZE = 200000;

function GetSteamInstallPath(): String;
var
  Path: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath', Path) then
  begin
    if Path <> '' then
    begin
      Result := Path;
      Exit;
    end;
  end;
  if RegQueryStringValue(HKCU, 'Software\Valve\Steam', 'InstallPath', Path) then
  begin
    if Path <> '' then
    begin
      Result := Path;
      Exit;
    end;
  end;
  if DirExists(ExpandConstant('{pf32}\Steam')) then
    Result := ExpandConstant('{pf32}\Steam');
end;

function GetFileSizeBytes(const FileName: String): Int64;
var
  FindRec: TFindRec;
begin
  Result := 0;
  if FindFirst(FileName, FindRec) then
  try
    Result := FindRec.SizeLow;
  finally
    FindClose(FindRec);
  end;
end;

function NeedsXInputInstall(const DestPath: String): Boolean;
begin
  if not FileExists(DestPath) then
  begin
    Result := True;
    Exit;
  end;
  Result := GetFileSizeBytes(DestPath) < MIN_XINPUT_DLL_SIZE;
end;

procedure StopSteamIfRunning();
var
  ResultCode: Integer;
begin
  if Exec('taskkill', '/F /IM steam.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    Sleep(2000);
end;

procedure InstallXInputToSteam();
var
  SteamPath, SrcDll, DestDll: String;
  ResultCode: Integer;
begin
  SteamPath := GetSteamInstallPath();
  if SteamPath = '' then
  begin
    Log('Steam install path not found — skipped xinput1_4.dll setup.');
    Exit;
  end;

  SrcDll := ExpandConstant('{app}\xinput1_4.dll');
  DestDll := SteamPath + '\xinput1_4.dll';

  if not FileExists(SrcDll) then
  begin
    Log('Bundled xinput1_4.dll missing in installer package.');
    Exit;
  end;

  if not NeedsXInputInstall(DestDll) then
  begin
    Log('xinput1_4.dll already present in Steam — skipped.');
    Exit;
  end;

  StopSteamIfRunning();

  if FileExists(DestDll) then
    DeleteFile(DestDll);

  if CopyFile(SrcDll, DestDll, False) then
    Log('xinput1_4.dll installed to: ' + DestDll)
  else
    MsgBox(
      'GameInSteam could not install xinput1_4.dll to your Steam folder.' + #13#10 +
      'Path: ' + DestDll + #13#10#13#10 +
      'Run the installer as Administrator or copy xinput1_4.dll manually.',
      mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    InstallXInputToSteam();
end;

function InitializeSetup(): Boolean;
var
  OldVersion: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\{#MyAppName}', 'Version', OldVersion) then
  begin
    if OldVersion <> '{#MyAppVersion}' then
    begin
      if MsgBox(
        '{#MyAppName} v' + OldVersion + ' is already installed.' + #13#10 +
        'Do you want to upgrade to v{#MyAppVersion}?',
        mbConfirmation, MB_YESNO) = IDNO then
      begin
        Result := False;
      end;
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  if MsgBox(
    'Are you sure you want to uninstall {#MyAppName}?' + #13#10 +
    'Your Steam library will NOT be affected.',
    mbConfirmation, MB_YESNO) = IDNO then
  begin
    Result := False;
  end;
end;
