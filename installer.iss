; NILKON installer (Inno Setup 6)
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6D1B2E58-7A0C-4C5E-9B64-4E1B6E0A9F11}
AppName=NILKON
AppVersion={#AppVersion}
AppPublisher=NILKON
DefaultDirName={autopf}\NILKON
DefaultGroupName=NILKON
UninstallDisplayIcon={app}\NILKON.exe
SetupIconFile=assets\logo.ico
OutputDir=installer_output
OutputBaseFilename=NILKON_Setup_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\NILKON\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NILKON"; Filename: "{app}\NILKON.exe"
Name: "{autodesktop}\NILKON"; Filename: "{app}\NILKON.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NILKON.exe"; Description: "Start NILKON"; Flags: nowait postinstall skipifsilent
