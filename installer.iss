; =============================================
; GameInSteam - Inno Setup Installer Script
; =============================================
; Basit ve kullanıcı dostu kurulum - Sadece Next Next Finish!

#define MyAppName "GameInSteam"
#define MyAppVersion "4.5"
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

; Basit ve hızlı kurulum
WizardSizePercent=110
DisableWelcomePage=no
DisableDirPage=no
DisableReadyPage=no
DisableFinishedPage=no

; Çalışan uygulamaları otomatik kapat
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
; Tüm task'lar otomatik seçili ve zorunlu
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "installdll"; Description: "Install xinput1_4.dll to Steam directory (required)"; Flags: checkedonce

[Files]
; Ana EXE dosyası - Çalışan uygulamayı kapat ve değiştir
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion restartreplace

; xinput1_4.dll - Steam dizinine otomatik kopyala
Source: "xinput1_4.dll"; DestDir: "{commonpf32}\Steam"; Tasks: installdll; Flags: ignoreversion uninsneveruninstall

; README
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Visual C++ Redistributables - Sessiz ve otomatik kurulum
Filename: "{sys}\powershell.exe"; Parameters: "-ExecutionPolicy Bypass -WindowStyle Hidden -NoProfile -Command ""$ErrorActionPreference='Stop';try{{if(-not(Test-Path 'HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64')){{$url='https://aka.ms/vs/17/release/vc_redist.x64.exe';$out='{tmp}\vc_redist.x64.exe';[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop;Start-Process -FilePath $out -ArgumentList '/quiet','/norestart' -Wait -NoNewWindow;Remove-Item $out -Force -ErrorAction SilentlyContinue}}}}catch{{}}"""; StatusMsg: "Installing required components..."; Check: VCRedistNeedsInstall; Flags: runhidden waituntilterminated

; Ana uygulama - Kurulum sonrası başlat (opsiyonel)
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\*"

[Code]
// Visual C++ Redistributables kontrolü - Basit ve hızlı
function IsVCRedistInstalled(): Boolean;
var
  Version: String;
begin
  Result := False;
  // Ana kontrol - Visual C++ 2015-2022 Redistributables (x64)
  if RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) then
  begin
    Result := True;
    Exit;
  end;
  // WOW64 kontrolü
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Version', Version) then
  begin
    Result := True;
    Exit;
  end;
  // Key varlık kontrolü
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

// Çalışan GameInSteam.exe'yi kapat
function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  
  // Çalışan GameInSteam.exe'yi kapat
  while True do
  begin
    if Exec('taskkill', '/F /IM GameInSteam.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      // Başarılı - uygulama kapatıldı
      Sleep(500); // Kısa bir bekleme
      Break;
    end
    else
    begin
      // Uygulama zaten kapalı veya bulunamadı
      Break;
    end;
  end;
  
  // Kısa bir bekleme daha (dosya kilidinin açılması için)
  Sleep(1000);
end;

// Kurulum sonrası - Basit mesaj
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Sadece basit bir bilgilendirme
    MsgBox('✅ Installation complete!' + #13#10#13#10 +
           'GameInSteam has been installed successfully.' + #13#10#13#10 +
           '⚠️ Please restart Steam before using GameInSteam!',
           mbInformation, MB_OK);
  end;
end;
