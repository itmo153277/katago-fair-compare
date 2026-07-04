
#define MyAppName "KataGo Fair Compare"
#define MyAppVersion "0.1"
#define MyAppPublisher "viktprog@gmail.com"
#define MyAppExeName "katago-fair-compare.exe"

[Setup]
AppId={{F812B871-1652-4B63-B84C-A8A58BA89CEB}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}
VersionInfoCopyright={#MyAppPublisher}
DefaultDirName={autopf}\KatagoFairCompare
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
OutputBaseFilename=katago-fair-compare-installer
Compression=lzma2/max
SolidCompression=yes
WizardStyle=classic
DisableWelcomePage=no
WizardImageFile=compiler:WizClassicImage.bmp
WizardSmallImageFile=compiler:WizClassicSmallImage.bmp
SetupIconFile=compiler:SetupClassicIcon.ico
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\katago-fair-compare\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\katago-fair-compare\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
