#define AppName "Lyricrafter Studio"
#define AppVersion "0.1.0"
#define AppPublisher "Jaylex32"
#define AppExeName "Lyricrafter.exe"

#ifndef DistDir
#define DistDir "..\dist-release\Lyricrafter"
#endif

#ifndef InstallerOutputDir
#define InstallerOutputDir "..\release\windows-installer"
#endif

[Setup]
AppId={{A4D33D85-03E4-4AD5-928C-E6966CEFF394}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Lyricrafter
DefaultGroupName=Lyricrafter
DisableProgramGroupPage=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename=Lyricrafter-Windows-x64-Setup
SetupIconFile=icons\lyricrafter.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=1900000000
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription=Local AI synchronized lyric studio
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=Copyright (C) 2026 {#AppPublisher}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Lyricrafter"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Lyricrafter"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Lyricrafter"; Flags: nowait postinstall skipifsilent
