#define AppName "ComTray"
#define AppVersion "1.1.0"

[Setup]
AppId={{6E1B0C4A-7D2F-4B8E-9C3A-COMTRAY00001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Davy Eprinchard
AppPublisherURL=https://github.com/Darkmind64/ComTray
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=ComTray-Setup-{#AppVersion}
SetupIconFile=comtray.ico
UninstallDisplayIcon={app}\ComTray.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "autostart"; Description: "Lancer ComTray au démarrage de Windows"; GroupDescription: "Options :"
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Options :"; Flags: unchecked

[Files]
Source: "dist\app\ComTray\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ComTray"; Filename: "{app}\ComTray.exe"
Name: "{group}\Désinstaller ComTray"; Filename: "{uninstallexe}"
Name: "{userdesktop}\ComTray"; Filename: "{app}\ComTray.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ComTray"; ValueData: """{app}\ComTray.exe"""; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "ComTray"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\ComTray.exe"; Description: "Lancer ComTray"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/F /IM ComTray.exe"; Flags: runhidden; RunOnceId: "KillComTray"


[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var R: Integer;
begin
  Exec('taskkill.exe', '/F /IM ComTray.exe', '', SW_HIDE, ewWaitUntilTerminated, R);
  Sleep(500);
  Result := '';
end;
