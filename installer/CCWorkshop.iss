#define AppVersion "0.2.0"
[Setup]
AppId={{0F451A3D-78FC-45AF-9D46-D938D669C3D9}
AppName=CC Workshop
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\CC Workshop
DefaultGroupName=CC Workshop
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=CCWorkshop-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\CCWorkshop.exe

[Files]
Source: "..\dist\CCWorkshop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\CC Workshop"; Filename: "{app}\CCWorkshop.exe"
Name: "{autodesktop}\CC Workshop"; Filename: "{app}\CCWorkshop.exe"

[Run]
Filename: "{app}\CCWorkshop.exe"; Description: "Launch CC Workshop"; Flags: nowait postinstall skipifsilent
